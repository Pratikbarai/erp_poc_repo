import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime
from frappe import _
from apparel_erp.product_development.doctype.style.style import advance_stage_at_least


class DesignTechPack(Document):
	def validate(self):
		if not self.created_on:
			self.created_on = frappe.db.get_value("Style", self.style, "creation")
		self.last_updated_on = now_datetime()
		self.last_updated_by = frappe.session.user

	def before_insert(self):
		if not self.created_on:
			self.created_on = frappe.utils.today()

	def after_insert(self):
		if self.style:
			advance_stage_at_least(self.style, "Design & Tech Pack")


@frappe.whitelist()
def get_style_snapshot(style):
	"""Read-only data the client renders for Colourways / Size Range / Fabric & Trims.
	Kept server-side (rather than a raw client frappe.db.get_doc) so a user only needs
	read access to the Style, not necessarily full doctype metadata permissions."""
	if not frappe.has_permission("Style", "read", style):
		frappe.throw(_("Not permitted to read Style {0}").format(style))

	style_doc = frappe.get_doc("Style", style)

	colours = [
		{
			"colour_name": c.colour_name,
			"colour_code": c.colour_code,
			"swatch": c.swatch,
			"status": c.status
		}
		for c in style_doc.colours
	]

	sizes = []
	for s in style_doc.sizes:
		size_code = frappe.db.get_value("Size", s.size, "size_code") or s.size
		sizes.append({"size": s.size, "size_code": size_code})

	bom_items = [
		{
			"item_type": b.item_type,
			"item_name": b.item_name,
			"description": b.description,
			"composition": b.composition,
			"gsm": b.gsm,
			"consumption": b.consumption,
			"uom": b.uom,
			"base_qty": b.base_qty,
			"tolerance": b.tolerance
		}
		for b in style_doc.bom_items
	]

	return {"colours": colours, "sizes": sizes, "bom_items": bom_items}


@frappe.whitelist()
def get_activity_feed(name):
	"""Merge user Comments with a plain-English reading of the Version log
	(field changes, child table row add/remove) into one feed, newest first."""
	import json

	feed = []

	comments = frappe.get_all(
		"Comment",
		filters={"reference_doctype": "Design Tech Pack", "reference_name": name, "comment_type": "Comment"},
		fields=["content", "owner", "creation"]
	)
	for c in comments:
		feed.append({
			"owner": c.owner,
			"creation": c.creation,
			"message": frappe.utils.strip_html(c.content or "")
		})

	info_comments = frappe.get_all(
		"Comment",
		filters={"reference_doctype": "Design Tech Pack", "reference_name": name, "comment_type": "Info"},
		fields=["content", "owner", "creation"]
	)
	for c in info_comments:
		feed.append({
			"owner": c.owner,
			"creation": c.creation,
			"message": frappe.utils.strip_html(c.content or "")
		})

	versions = frappe.get_all(
		"Version",
		filters={"ref_doctype": "Design Tech Pack", "docname": name},
		fields=["data", "owner", "creation"],
		order_by="creation asc"
	)
	for v in versions:
		try:
			data = json.loads(v.data)
		except Exception:
			continue

		messages = []
		for changed in data.get("changed", []):
			if len(changed) < 3:
				continue
			fieldname, old, new = changed[0], changed[1], changed[2]
			if fieldname in ("last_updated_on", "last_updated_by", "modified"):
				continue
			label = fieldname.replace("_", " ").title()
			if old in (None, "") and new not in (None, ""):
				messages.append(_("Set {0}").format(label))
			elif new in (None, ""):
				messages.append(_("Cleared {0}").format(label))
			else:
				messages.append(_("Updated {0}").format(label))

		for row_change in data.get("row_changed", []):
			table_field = row_change[0]
			messages.append(_("Updated a row in {0}").format(table_field.replace("_", " ").title()))

		added = data.get("added", [])
		for a in added:
			messages.append(_("Added a row to {0}").format(str(a[0]).replace("_", " ").title()))

		removed = data.get("removed", [])
		for r in removed:
			messages.append(_("Removed a row from {0}").format(str(r[0]).replace("_", " ").title()))

		if messages:
			# de-duplicate while keeping order
			seen = []
			for m in messages:
				if m not in seen:
					seen.append(m)
			feed.append({
				"owner": v.owner,
				"creation": v.creation,
				"message": ", ".join(seen)
			})

	feed.sort(key=lambda x: x["creation"], reverse=True)
	return feed[:30]


@frappe.whitelist()
def send_for_sampling(name, assign_to=None):
	doc = frappe.get_doc("Design Tech Pack", name)

	if assign_to:
		doc.assign_to = assign_to
		doc.save(ignore_permissions=True)

		if not frappe.db.exists("ToDo", {"reference_type": "Design Tech Pack", "reference_name": name, "status": "Open"}):
			frappe.get_doc({
				"doctype": "ToDo",
				"allocated_to": assign_to,
				"reference_type": "Design Tech Pack",
				"reference_name": name,
				"description": _("Tech pack for {0} is ready - please proceed with sampling.").format(doc.style)
			}).insert(ignore_permissions=True)

	doc.add_comment("Info", _("Sent for Sampling, assigned to {0}").format(assign_to or _("(unassigned)")))
	if doc.style:
		advance_stage_at_least(doc.style, "Sampling")
	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist()
def set_status(name, status):
	if status not in ("Not Started", "In Progress", "Completed"):
		frappe.throw(_("Unknown status: {0}").format(status))
	doc = frappe.get_doc("Design Tech Pack", name)
	doc.status = status
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist()
def mark_as_completed(name):
	"""Kept for backwards compatibility - prefer set_status(name, 'Completed')."""
	return set_status(name, "Completed")
