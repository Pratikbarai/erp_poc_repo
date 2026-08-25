import frappe
from frappe.model.document import Document
from frappe import _

WORKFLOW_STAGES = [
	"Style Created",
	"Design & Tech Pack",
	"Sampling",
	"Fit Approval",
	"Proto Approval",
	"Production"
]

STYLE_STATUSES = ("Not Started", "In Progress", "Completed")


class Style(Document):
	def validate(self):
		if (self.status or "Not Started") not in STYLE_STATUSES:
			frappe.throw(_("Status must be one of: {0}").format(", ".join(STYLE_STATUSES)))
		self.sync_matrix_rows()
		if not self.development_stage:
			self.development_stage = "Style Created"

	def sync_matrix_rows(self):
		"""Whenever Colours or Sizes change, make sure every Colour x Size
		combination has a placeholder row in matrix_items. Existing rows
		(already generated SKUs) are never removed automatically."""
		existing_keys = {
			(row.colour_code, row.size_code): row for row in self.matrix_items
		}

		active_colours = [c for c in self.colours if (c.status or "Active") == "Active"]

		for colour in active_colours:
			colour_code = colour.colour_code or colour.colour_name
			for size_row in self.sizes:
				size_doc_code = frappe.db.get_value("Size", size_row.size, "size_code") or size_row.size
				key = (colour_code, size_doc_code)
				if key not in existing_keys:
					self.append("matrix_items", {
						"colour": colour.colour_name,
						"colour_code": colour_code,
						"size": size_row.size,
						"size_code": size_doc_code,
						"status": "Not Generated"
					})


@frappe.whitelist()
def set_development_stage(style, stage):
	"""Manually advance/rewind the workflow stepper on the Development Workflow tab."""
	if stage not in WORKFLOW_STAGES:
		frappe.throw(_("Unknown stage: {0}").format(stage))
	frappe.db.set_value("Style", style, "development_stage", stage)
	frappe.db.commit()
	return {"development_stage": stage}


def advance_stage_at_least(style, stage):
	"""Called from Design Tech Pack - push the Style forward to `stage` unless it is
	already at or past it. Never moves the stepper backwards automatically."""
	if stage not in WORKFLOW_STAGES:
		return
	current = frappe.db.get_value("Style", style, "development_stage") or "Style Created"
	if WORKFLOW_STAGES.index(stage) > WORKFLOW_STAGES.index(current):
		frappe.db.set_value("Style", style, "development_stage", stage)


@frappe.whitelist()
def generate_sku(style, colour_code, size_code):
	"""Called when a user clicks an empty (or existing) matrix cell.
	Creates the Item (SKU) + a base BOM from the style's BOM table if they
	don't already exist, links them on the matrix row, and returns the
	Item name so the client can redirect to it. Also generates all pending
	SKUs + BOMs and submits the Style."""

	style_doc = frappe.get_doc("Style", style)
	if not style_doc.bom_items:
		frappe.throw(_("Add at least one BOM Item before generating SKUs."))

	target_row = None
	for row in style_doc.matrix_items:
		if row.colour_code == colour_code and row.size_code == size_code:
			target_row = row
			break

	if not target_row:
		frappe.throw(_("Matrix cell not found for {0} / {1}").format(colour_code, size_code))

	# Idempotent: if already generated, just return it (used for redirect-on-click too)
	if target_row.item and frappe.db.exists("Item", target_row.item):
		# Even if already generated, still generate all pending SKUs
		pass

	material_token = _get_material_sku_token(style_doc)
	sku = f"{style_doc.style_no}-{colour_code}-{size_code}-{material_token}"
	colour_row = next((c for c in style_doc.colours if c.colour_code == colour_code or c.colour_name == colour_code), None)

	if not frappe.db.exists("Item", sku):
		item = frappe.new_doc("Item")
		item.item_code = sku
		item.item_name = f"{style_doc.style_name} - {colour_row.colour_name if colour_row else colour_code} - {size_code}"
		item.item_group = _get_or_create_item_group(style_doc.product_type or "Finished Goods")
		item.stock_uom = "Nos"
		item.is_stock_item = 1
		item.description = style_doc.description
		if style_doc.style_image:
			item.image = style_doc.style_image
		item.insert(ignore_permissions=True)
	else:
		item = frappe.get_doc("Item", sku)

	bom_name = None
	if style_doc.bom_items:
		bom_name = _create_bom_for_item(style_doc, item)

	target_row.sku = sku
	target_row.item = item.name
	target_row.bom = bom_name
	target_row.status = "Active"

	# Generate ALL pending SKUs + BOMs
	pending_rows = [r for r in style_doc.matrix_items if r.status == "Not Generated"]
	for pending_row in pending_rows:
		p_colour_code = pending_row.colour_code
		p_size_code = pending_row.size_code
		p_sku = f"{style_doc.style_no}-{p_colour_code}-{p_size_code}-{material_token}"
		p_colour_row = next((c for c in style_doc.colours if c.colour_code == p_colour_code or c.colour_name == p_colour_code), None)
		
		if not frappe.db.exists("Item", p_sku):
			p_item = frappe.new_doc("Item")
			p_item.item_code = p_sku
			p_item.item_name = f"{style_doc.style_name} - {p_colour_row.colour_name if p_colour_row else p_colour_code} - {p_size_code}"
			p_item.item_group = _get_or_create_item_group(style_doc.product_type or "Finished Goods")
			p_item.stock_uom = "Nos"
			p_item.is_stock_item = 1
			p_item.description = style_doc.description
			if style_doc.style_image:
				p_item.image = style_doc.style_image
			p_item.insert(ignore_permissions=True)
		else:
			p_item = frappe.get_doc("Item", p_sku)
		
		p_bom_name = _create_bom_for_item(style_doc, p_item)
		
		# Find and update the pending row
		for pr in style_doc.matrix_items:
			if pr.colour_code == p_colour_code and pr.size_code == p_size_code:
				pr.sku = p_sku
				pr.item = p_item.name
				pr.bom = p_bom_name
				pr.status = "Active"
				break

	style_doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {"item": item.name, "sku": sku, "bom": bom_name, "created": True}


def _get_material_sku_token(style_doc):
	"""Build one stable SKU token from all material rows on the Style."""
	tokens = []
	for row in style_doc.bom_items:
		material = row.raw_material or row.item_name
		token = frappe.scrub(material).upper().replace("_", "-")
		if token and token not in tokens:
			tokens.append(token)
	return "-".join(tokens)


def _get_or_create_item_group(name):
	if not frappe.db.exists("Item Group", name):
		ig = frappe.new_doc("Item Group")
		ig.item_group_name = name
		ig.parent_item_group = frappe.db.get_value(
			"Item Group", {"is_group": 1}, "name"
		) or "All Item Groups"
		ig.insert(ignore_permissions=True)
	return name


def _get_or_create_component_item(row):
	"""Ensure a raw material / trim / packaging Item exists for a Style BOM row
	so the generated BOM has something valid to point to."""
	if row.raw_material and frappe.db.exists("Item", row.raw_material):
		return row.raw_material

	code = frappe.scrub(row.item_name).upper().replace(" ", "-")
	if not frappe.db.exists("Item", code):
		comp = frappe.new_doc("Item")
		comp.item_code = code
		comp.item_name = row.item_name
		comp.item_group = _get_or_create_item_group(row.item_type or "Raw Material")
		comp.stock_uom = row.uom or "Nos"
		comp.is_stock_item = 1
		comp.insert(ignore_permissions=True)
	return code


def _create_bom_for_item(style_doc, item):
	existing = frappe.db.get_value(
		"BOM", {"item": item.item_code, "is_active": 1, "docstatus": ["<", 2]}, "name"
	)
	if existing:
		existing_bom = frappe.get_doc("BOM", existing)
		if existing_bom.docstatus == 0:
			existing_bom.submit()
		return existing_bom.name

	bom = frappe.new_doc("BOM")
	bom.item = item.item_code
	bom.quantity = 1
	bom.is_active = 1
	bom.is_default = 1
	bom.with_operations = 0

	for row in style_doc.bom_items:
		component_code = _get_or_create_component_item(row)
		bom.append("items", {
			"item_code": component_code,
			"qty": row.base_qty or 1,
			"uom": row.uom
		})

	bom.insert(ignore_permissions=True)
	bom.submit()
	return bom.name
