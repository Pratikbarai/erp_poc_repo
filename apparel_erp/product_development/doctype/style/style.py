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
MATRIX_ITEM_STATUSES = ("Active", "Drop", "On Hold")


class Style(Document):
	def validate(self):
		if (self.status or "Not Started") not in STYLE_STATUSES:
			frappe.throw(_("Status must be one of: {0}").format(", ".join(STYLE_STATUSES)))
		self.validate_base_style()
		previous = self.get_doc_before_save()
		if not previous:
			self.bom_version = "1.0"
		elif self.has_value_changed("bom_items"):
			self.bom_version = _next_version(previous.bom_version or "1.0")
		else:
			self.bom_version = previous.bom_version or "1.0"
		for row in self.bom_items:
			if row.raw_material:
				item_data = frappe.db.get_value("Item", row.raw_material, ["item_name", "item_code"], as_dict=True)
				if item_data:
					row.item_name = item_data.item_name
		self.sync_matrix_rows()
		if not self.development_stage:
			self.development_stage = "Style Created"

	def validate_base_style(self):
		if not self.base_style:
			return
		seen = {self.name}
		current = self.base_style
		while current:
			if current in seen:
				frappe.throw(_("Base Style cannot reference itself or create a cycle."))
			seen.add(current)
			current = frappe.db.get_value("Style", current, "base_style")


def get_effective_bom_items(style_doc):
	"""Use this Style's BOM, or walk up the Base Style chain when it has none."""
	if style_doc.bom_items:
		return style_doc.bom_items
	seen = {style_doc.name}
	current = style_doc.base_style
	while current:
		if current in seen:
			frappe.throw(_("Base Style cycle detected while loading BOM materials."))
		seen.add(current)
		base_doc = frappe.get_doc("Style", current)
		if base_doc.bom_items:
			return base_doc.bom_items
		current = base_doc.base_style
	return []

	def sync_matrix_rows(self):
		"""Whenever Colours or Sizes change, make sure every Colour x Size
		combination has a placeholder row in matrix_items. Existing rows
		(already generated SKUs) are never removed automatically."""
		existing_keys = {
			(row.colour_code, row.size_code): row for row in self.matrix_items
		}
		for row in self.matrix_items:
			if row.item and (not row.item_name or not row.item_code):
				item_data = frappe.db.get_value(
					"Item", row.item, ["item_name", "item_code"], as_dict=True
				)
				if item_data:
					row.item_name = item_data.item_name
					row.item_code = item_data.item_code

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
	bom_items = get_effective_bom_items(style_doc)
	if not bom_items:
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

	sku = f"{style_doc.style_no}-{colour_code}-{size_code}"
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
		bom_name = _create_bom_for_item(style_doc, item, bom_items)

	target_row.sku = sku
	target_row.item = item.name
	target_row.item_name = item.item_name
	target_row.item_code = item.item_code
	target_row.bom = bom_name
	target_row.status = "Active"

	# Generate ALL pending SKUs + BOMs
	pending_rows = [r for r in style_doc.matrix_items if r.status == "Not Generated"]
	for pending_row in pending_rows:
		p_colour_code = pending_row.colour_code
		p_size_code = pending_row.size_code
		p_sku = f"{style_doc.style_no}-{p_colour_code}-{p_size_code}"
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
		
		p_bom_name = _create_bom_for_item(style_doc, p_item, bom_items)
		
		# Find and update the pending row
		for pr in style_doc.matrix_items:
			if pr.colour_code == p_colour_code and pr.size_code == p_size_code:
				pr.sku = p_sku
				pr.item = p_item.name
				pr.item_name = p_item.item_name
				pr.item_code = p_item.item_code
				pr.bom = p_bom_name
				pr.status = "Active"
				break

	style_doc.save(ignore_permissions=True)
	frappe.db.commit()

	generated_count = sum(1 for row in style_doc.matrix_items if row.item and row.bom and row.status == "Active")
	return {
		"item": item.name,
		"sku": sku,
		"bom": bom_name,
		"generated_count": generated_count,
		"material_count": len(bom_items),
		"created": True
	}


@frappe.whitelist()
def set_matrix_item_status(style, matrix_item, status):
	if status not in MATRIX_ITEM_STATUSES:
		frappe.throw(_("Status must be one of: {0}").format(", ".join(MATRIX_ITEM_STATUSES)))

	style_doc = frappe.get_doc("Style", style)
	target_row = next((row for row in style_doc.matrix_items if row.name == matrix_item), None)
	if not target_row:
		frappe.throw(_("Matrix item not found: {0}").format(matrix_item))
	if not target_row.item:
		frappe.throw(_("Generate the SKU before setting its status."))

	target_row.status = status
	style_doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"status": status}


def _get_or_create_item_group(name):
	if not frappe.db.exists("Item Group", name):
		ig = frappe.new_doc("Item Group")
		ig.item_group_name = name
		ig.parent_item_group = frappe.db.get_value(
			"Item Group", {"is_group": 1}, "name"
		) or "All Item Groups"
		ig.insert(ignore_permissions=True)
	return name


def _next_version(version):
	try:
		major, minor = str(version).lstrip("v").split(".", 1)
		return f"{major}.{int(minor) + 1}"
	except (ValueError, AttributeError):
		return "1.1"


@frappe.whitelist()
def get_bom_version_history(style):
	style_doc = frappe.get_doc("Style", style)
	if not frappe.has_permission("Style", "read", doc=style_doc):
		frappe.throw(_("Not permitted to read Style {0}").format(style))

	import json
	history = []
	versions = frappe.get_all(
		"Version",
		filters={"ref_doctype": "Style", "docname": style},
		fields=["data", "owner", "creation"],
		order_by="creation desc",
		limit_page_length=20
	)
	for version in versions:
		try:
			data = json.loads(version.data)
		except (TypeError, ValueError):
			continue

		changes = []
		for changed in data.get("changed", []):
			if len(changed) >= 3 and changed[0] in ("bom_version", "bom_items"):
				changes.append({"field": changed[0], "old": changed[1], "new": changed[2]})
		for row_change in data.get("row_changed", []):
			if row_change and row_change[0] == "bom_items":
				changes.append({"field": "bom_items", "detail": row_change[1:]})
		for row in data.get("added", []):
			if row and row[0] == "bom_items":
				changes.append({"field": "bom_items", "detail": ["Added", row[1:]]})
		for row in data.get("removed", []):
			if row and row[0] == "bom_items":
				changes.append({"field": "bom_items", "detail": ["Removed", row[1:]]})
		if changes:
			history.append({"version": next((c["new"] for c in changes if c["field"] == "bom_version"), "Revision"), "owner": version.owner, "creation": version.creation, "changes": changes})

	return history


def _get_or_create_component_item(row):
	"""Ensure a raw material / trim / packaging Item exists for a Style BOM row
	so the generated BOM has something valid to point to."""
	if row.raw_material and frappe.db.exists("Item", row.raw_material):
		return row.raw_material
	if not row.item_name:
		frappe.throw(_("Select an existing Item or enter a new Item Name."))

	code = row.new_item_code or frappe.scrub(row.item_name).upper().replace(" ", "-")
	if not frappe.db.exists("Item", code):
		comp = frappe.new_doc("Item")
		comp.item_code = code
		comp.item_name = row.item_name
		comp.item_group = _get_or_create_item_group(row.item_type or "Raw Material")
		comp.stock_uom = row.uom or "Nos"
		comp.is_stock_item = 1
		comp.insert(ignore_permissions=True)
	return code


def _create_bom_for_item(style_doc, item, bom_items=None):
	bom_items = bom_items if bom_items is not None else get_effective_bom_items(style_doc)
	if not bom_items:
		frappe.throw(_("Add at least one BOM material before generating SKUs."))

	existing = frappe.db.get_value(
		"BOM", {"item": item.item_code, "is_active": 1, "docstatus": ["<", 2]}, "name"
	)
	if existing:
		existing_bom = frappe.get_doc("BOM", existing)
		if not existing_bom.items:
			frappe.throw(_("BOM {0} has no materials for Item {1}.").format(existing_bom.name, item.item_code))
		if existing_bom.docstatus == 0:
			existing_bom.submit()
		return existing_bom.name

	bom = frappe.new_doc("BOM")
	bom.item = item.item_code
	bom.quantity = 1
	bom.is_active = 1
	bom.is_default = 1
	bom.with_operations = 0

	for row in bom_items:
		component_code = _get_or_create_component_item(row)
		bom.append("items", {
			"item_code": component_code,
			"qty": row.base_qty or 1,
			"uom": row.uom
		})

	bom.insert(ignore_permissions=True)
	bom.submit()
	return bom.name
