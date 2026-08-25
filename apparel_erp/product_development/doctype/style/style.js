const WORKFLOW_STAGES = [
	"Style Created",
	"Design & Tech Pack",
	"Sampling",
	"Fit Approval",
	"Proto Approval",
	"Production"
];
frappe.ui.form.on("Style", {
	refresh(frm) {
		render_matrix(frm);
		render_gallery(frm);
		render_workflow(frm);
		render_status_dropdown(frm);
		render_size_chart_preview(frm);

		if (!frm.is_new()) {
			frm.add_custom_button(__("Open Style Workspace"), () => {
				frappe.set_route("style-workspace", frm.doc.name);
			}).addClass("btn-primary");
		}

		frm.add_custom_button(__("Sync Matrix"), () => {
			frm.save().then(() => render_matrix(frm));
		});

		frm.add_custom_button(__("Generate All SKUs"), () => {
			generate_all_skus(frm);
		});

		if (!frm.is_new()) {
			frm.add_custom_button(__("Design & Tech Pack"), () => open_tech_pack(frm));
		}

		if (frm.doc.size_chart) {
			frm.add_custom_button(__("Size Chart"), () => window.open(frm.doc.size_chart, "_blank"));
		}

		render_style_image_preview(frm);
	},

	development_stage(frm) {
		render_workflow(frm);
	},

	// Table MultiSelect fires the fieldname event on add/remove, same as a normal field
	sizes(frm) {
		sync_and_render(frm);
	},

	colours_add(frm) {
		sync_and_render(frm);
	},

	colours_remove(frm) {
		sync_and_render(frm);
	},

	onload(frm) {
		render_matrix(frm);
		render_style_image_preview(frm);
		render_size_chart_preview(frm);
	}
});

function render_style_image_preview(frm) {
	if (!frm.doc.style_image) return;
	const $wrapper = frm.get_field("style_image").$wrapper;
	$wrapper.find("img").css("max-width", "100%").css("height", "auto");
	$wrapper.find("a").off("click").on("click", function(e) {
		e.preventDefault();
		frappe.show_alert({ message: __("Image preview"), indicator: "info" });
	});
}

function render_size_chart_preview(frm) {
	if (!frm.doc.size_chart || !/\.(png|jpe?g|gif|webp|bmp)(\?.*)?$/i.test(frm.doc.size_chart)) return;
	const $wrapper = frm.get_field("size_chart").$wrapper;
	if ($wrapper.find(".apparel-size-chart-preview").length) return;
	$wrapper.append(`<img src="${frm.doc.size_chart}" class="apparel-size-chart-preview" alt="${__("Size Chart")}">`);
	$wrapper.find(".apparel-size-chart-preview").css({
		"max-width": "160px",
		"max-height": "160px",
		"object-fit": "cover",
		"display": "block",
		"margin-top": "8px",
		"border": "1px solid var(--border-color)",
		"border-radius": "4px",
		"cursor": "pointer"
	}).on("click", () => window.open(frm.doc.size_chart, "_blank"));
}

function open_tech_pack(frm) {
	frappe.db.get_value("Design Tech Pack", { style: frm.doc.name }, "name").then(r => {
		if (r.message && r.message.name) {
			frappe.set_route("Form", "Design Tech Pack", r.message.name);
		} else {
			frappe.new_doc("Design Tech Pack", { style: frm.doc.name });
		}
	});
}

function sync_and_render(frm) {
	if (frm.is_new()) {
		render_matrix(frm);
		return;
	}
	frm.save().then(() => render_matrix(frm));
}

function render_matrix(frm) {
	const wrapper = frm.get_field("matrix_html").$wrapper;
	wrapper.empty();

	const colours = (frm.doc.colours || []).filter(c => (c.status || "Active") === "Active");
	const sizes = frm.doc.sizes || [];

	if (!colours.length || !sizes.length) {
		wrapper.html(`<div class="text-muted padding">${__(
			"Add at least one Colour and select Sizes above, then save, to generate the matrix."
		)}</div>`);
		return;
	}

	if (frm.is_new() || frm.is_dirty()) {
		wrapper.html(`<div class="text-muted padding">
			${__("Save the Style to build the Colour x Size matrix.")}
		</div>`);
		return;
	}

	let html = `<div class="table-responsive"><table class="table table-bordered apparel-matrix">
		<thead><tr><th>${__("Colour")}</th>`;
	sizes.forEach(s => {
		html += `<th class="text-center">${frappe.utils.escape_html(s.size)}</th>`;
	});
	html += `</tr></thead><tbody>`;

	colours.forEach(colour => {
		const colour_code = colour.colour_code || colour.colour_name;
		html += `<tr><td><strong>${frappe.utils.escape_html(colour.colour_name)}</strong>`;
		if (colour.swatch) {
			html += ` <span class="indicator-pill" style="background:${colour.swatch}">&nbsp;</span>`;
		}
		html += `</td>`;

		sizes.forEach(size_row => {
			const size_code = get_size_code(frm, size_row.size);
			const matrix_row = (frm.doc.matrix_items || []).find(
				m => m.colour_code === colour_code && m.size_code === size_code
			);

			html += `<td class="text-center apparel-matrix-cell" data-colour="${colour_code}" data-size="${size_code}">`;
			if (matrix_row && matrix_row.item) {
				html += `<a href="#" class="matrix-sku matrix-generated" data-item="${matrix_row.item}">
					${matrix_row.sku}<br><span class="indicator green">${__("Active")}</span></a>`;
			} else if (matrix_row) {
				html += `<a href="#" class="matrix-sku matrix-empty">
					${__("+ Generate")}</a>`;
			} else {
				html += `<span class="text-muted">${__("--")}</span>`;
			}
			html += `</td>`;
		});
		html += `</tr>`;
	});

	html += `</tbody></table></div>
	<style>
		.apparel-matrix th, .apparel-matrix td { vertical-align: middle; }
		.apparel-matrix .matrix-sku { display: inline-block; padding: 6px 4px; }
		.apparel-matrix .matrix-empty { color: var(--text-muted); border: 1px dashed var(--dark-border-color); border-radius: 4px; padding: 6px 10px; }
		.apparel-matrix .matrix-generated { font-weight: 600; }
	</style>`;

	wrapper.html(html);

	wrapper.find(".matrix-sku").on("click", function (e) {
		e.preventDefault();
		const $cell = $(this).closest(".apparel-matrix-cell");
		const colour_code = $cell.attr("data-colour");
		const size_code = $cell.attr("data-size");
		const item = $(this).attr("data-item");

		if (item) {
			// already generated - just redirect straight to the Item (image preview, not a link)
			frappe.set_route("Form", "Item", item);
			return;
		}

		frappe.dom.freeze(__("Generating SKU & BOM..."));
		frappe.call({
			method: "apparel_erp.product_development.doctype.style.style.generate_sku",
			args: {
				style: frm.doc.name,
				colour_code: colour_code,
				size_code: size_code
			},
			callback: function (r) {
				frappe.dom.unfreeze();
				if (r.message && r.message.item) {
					frappe.show_alert({
						message: r.message.bom
							? __("SKU {0} and BOM {1} created", [r.message.item, r.message.bom])
							: __("SKU {0} created (add Style BOM items to generate a BOM)", [r.message.item]),
						indicator: "green"
					});
					// redirect straight into the Item form - Attach Image field
					// previews the style image inline, it is not shown as a bare link
					frappe.set_route("Form", "Item", r.message.item);
				}
			},
			error: function () {
				frappe.dom.unfreeze();
			}
		});
	});
}

function get_size_code(frm, size_link) {
	// pull from locals cache populated by the Size link field / fetched list
	const size_doc = frappe.get_doc("Size", size_link);
	if (size_doc && size_doc.size_code) return size_doc.size_code;
	return size_link;
}

function render_gallery(frm) {
	const $w = frm.get_field("gallery_html").$wrapper;
	$w.empty();

	let html = `<div class="tp-gallery-strip">`;
	(frm.doc.gallery || []).forEach((row, idx) => {
		const active = row.image === frm.doc.style_image;
		html += `<div class="tp-gallery-thumb ${active ? "active" : ""}" data-idx="${idx}">
			<img src="${row.image}">
			<span class="tp-gallery-remove" data-idx="${idx}" title="${__("Remove")}">&times;</span>
		</div>`;
	});
	html += `<div class="tp-gallery-add" title="${__("Add image")}">+</div></div>
	<style>
		.tp-gallery-strip{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;}
		.tp-gallery-thumb{position:relative;width:48px;height:48px;border-radius:6px;overflow:hidden;
			border:2px solid var(--border-color);cursor:pointer;}
		.tp-gallery-thumb.active{border-color:var(--primary);}
		.tp-gallery-thumb img{width:100%;height:100%;object-fit:cover;display:block;}
		.tp-gallery-remove{position:absolute;top:0;right:0;background:rgba(0,0,0,.6);color:#fff;
			font-size:11px;line-height:14px;width:14px;height:14px;text-align:center;border-radius:0 0 0 4px;}
		.tp-gallery-add{width:48px;height:48px;border:2px dashed var(--border-color);border-radius:6px;
			display:flex;align-items:center;justify-content:center;font-size:20px;color:var(--text-muted);cursor:pointer;}
	</style>`;

	$w.html(html);

	$w.find(".tp-gallery-thumb img").on("click", function () {
		const idx = $(this).closest(".tp-gallery-thumb").attr("data-idx");
		frm.set_value("style_image", frm.doc.gallery[idx].image);
	});

	$w.find(".tp-gallery-remove").on("click", function (e) {
		e.stopPropagation();
		const idx = $(this).attr("data-idx");
		frm.doc.gallery.splice(idx, 1);
		frm.refresh_field("gallery");
		render_gallery(frm);
		frm.dirty();
	});

	$w.find(".tp-gallery-add").on("click", () => {
		new frappe.ui.FileUploader({
			doctype: "Style",
			docname: frm.doc.name,
			on_success: (file) => {
				const row = frm.add_child("gallery", { image: file.file_url });
				if (!frm.doc.style_image) frm.set_value("style_image", file.file_url);
				frm.refresh_field("gallery");
				render_gallery(frm);
				frm.dirty();
			}
		});
	});
}

function render_workflow(frm) {
	const $w = frm.get_field("workflow_html").$wrapper;
	$w.empty();

	if (frm.is_new()) {
		$w.html(`<div class="text-muted">${__("Save the Style to see its workflow.")}</div>`);
		return;
	}

	const current = frm.doc.development_stage || "Style Created";
	const current_idx = WORKFLOW_STAGES.indexOf(current);

	let html = `<div class="tp-workflow-stepper">`;
	WORKFLOW_STAGES.forEach((stage, idx) => {
		let state = "pending";
		if (idx < current_idx) state = "done";
		else if (idx === current_idx) state = "active";

		html += `<div class="tp-wf-step">
			<div class="tp-wf-bubble ${state}" data-stage="${stage}" title="${__("Set as current stage")}">
				${state === "done" ? "&#10003;" : idx + 1}
			</div>
			<div class="tp-wf-label ${state}">${__(stage)}</div>
			<div class="tp-wf-sub">${state === "done" ? __("Done") : state === "active" ? __("In Progress") : __("Pending")}</div>
		</div>`;
		if (idx < WORKFLOW_STAGES.length - 1) {
			html += `<div class="tp-wf-connector ${idx < current_idx ? "done" : ""}"></div>`;
		}
	});
	html += `</div>
	<style>
		.tp-workflow-stepper{display:flex;align-items:flex-start;padding:16px 0;overflow-x:auto;}
		.tp-wf-step{display:flex;flex-direction:column;align-items:center;min-width:110px;text-align:center;}
		.tp-wf-bubble{width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;
			font-weight:600;cursor:pointer;border:2px solid var(--border-color);color:var(--text-muted);background:var(--fg-color);}
		.tp-wf-bubble.done{background:var(--dark-green-500,#2e8b57);border-color:var(--dark-green-500,#2e8b57);color:#fff;}
		.tp-wf-bubble.active{background:var(--yellow-500,#e0a800);border-color:var(--yellow-500,#e0a800);color:#fff;}
		.tp-wf-label{margin-top:6px;font-size:12px;font-weight:600;}
		.tp-wf-sub{font-size:11px;color:var(--text-muted);}
		.tp-wf-connector{height:2px;background:var(--border-color);flex:1;margin-top:19px;min-width:24px;}
		.tp-wf-connector.done{background:var(--dark-green-500,#2e8b57);}
	</style>`;

	$w.html(html);

	$w.find(".tp-wf-bubble").on("click", function () {
		const stage = $(this).attr("data-stage");
		if (stage === current) return;
		frappe.confirm(
			__("Set development stage to {0}?", [stage]),
			() => {
				frappe.call({
					method: "apparel_erp.product_development.doctype.style.style.set_development_stage",
					args: { style: frm.doc.name, stage },
					callback: () => {
						frm.doc.development_stage = stage;
						render_workflow(frm);
						frappe.show_alert({ message: __("Stage updated"), indicator: "green" });
					}
				});
			}
		);
	});
}

function render_status_dropdown(frm) {
	if (frm.is_new()) return;
	const statuses = ["Not Started", "In Progress", "Completed"];
	statuses
		.filter(s => s !== frm.doc.status)
		.forEach(s => {
			frm.add_custom_button(s, () => {
				frappe.db.set_value("Style", frm.doc.name, "status", s).then(() => {
					frm.reload_doc();
					frappe.show_alert({ message: __("Status set to {0}", [s]), indicator: "green" });
				});
			}, __("Set Status"));
		});
}

function render_rest_tab(frm) {
	const wrapper = frm.get_field("rest_api_html").$wrapper;
	wrapper.empty();

	if (frm.is_new()) {
		wrapper.html(`<div class="text-muted padding">${__(
			"Save the record to get its REST API endpoint."
		)}</div>`);
		return;
	}

	const base = window.location.origin;
	const resource_url = `${base}/api/resource/Style/${encodeURIComponent(frm.doc.name)}`;
	const curl = `curl -X GET "${resource_url}" \\\n  -H "Authorization: token <api_key>:<api_secret>"`;

	const html = `
		<div class="apparel-rest-tab">
			<h5>${__("Resource URL")}</h5>
			<div class="input-group" style="max-width:640px;">
				<input type="text" class="form-control" readonly value="${resource_url}">
				<div class="input-group-append">
					<button class="btn btn-default btn-sm copy-rest-url">${__("Copy")}</button>
				</div>
			</div>
			<h5 class="margin-top">${__("Example (cURL)")}</h5>
			<pre>${frappe.utils.escape_html(curl)}</pre>
			<h5 class="margin-top">${__("Common operations")}</h5>
			<ul>
				<li><b>GET</b> ${resource_url} - ${__("fetch this Style")}</li>
				<li><b>PUT</b> ${resource_url} - ${__("update this Style")}</li>
				<li><b>DELETE</b> ${resource_url} - ${__("delete this Style")}</li>
				<li><b>POST</b> ${base}/api/resource/Style - ${__("create a new Style")}</li>
				<li><b>POST</b> ${base}/api/method/apparel_erp.product_development.doctype.style.style.generate_sku - ${__("generate a matrix SKU + BOM programmatically")}</li>
			</ul>
		</div>`;

	wrapper.html(html);
	wrapper.find(".copy-rest-url").on("click", function () {
		frappe.utils.copy_to_clipboard(resource_url);
	});
}

function generate_all_skus(frm) {
	// Check if colours and sizes are available
	const colours = (frm.doc.colours || []).filter(c => (c.status || "Active") === "Active");
	const sizes = frm.doc.sizes || [];
	
	if (!colours.length || !sizes.length) {
		frappe.msgprint(__("Please add at least one Colour and select Sizes first."));
		return;
	}
	
	// Check if any matrix rows need generation
	const matrix_rows = frm.doc.matrix_items || [];
	const pending_rows = matrix_rows.filter(m => m.status === "Not Generated");
	
	if (!pending_rows.length) {
		frappe.msgprint(__("All SKUs are already generated."));
		render_matrix(frm);
		return;
	}
	
	frappe.confirm(
		__("Generate SKUs for all {0} Colour x Size combinations?", [pending_rows.length]),
		() => {
			frappe.dom.freeze(__("Generating all SKUs & BOMs..."));
			
			let generated = 0;
			let skipped = 0;
			
			pending_rows.forEach((row, idx) => {
				setTimeout(() => {
					frappe.call({
						method: "apparel_erp.product_development.doctype.style.style.generate_sku",
						args: {
							style: frm.doc.name,
							colour_code: row.colour_code,
							size_code: row.size_code
						},
						callback: function (r) {
							if (r.message && r.message.item) {
								generated++;
								// Update the row locally
								row.sku = r.message.sku;
								row.item = r.message.item;
								row.bom = r.message.bom;
								row.status = "Active";
								frm.refresh_field("matrix_items");
							} else {
								skipped++;
							}
							
							if (idx === pending_rows.length - 1) {
								frappe.dom.unfreeze();
								frappe.msgprint(__("Generated: {0}, Skipped: {1}", [generated, skipped]));
								render_matrix(frm);
							}
						}
					});
				}, idx * 500); // Small delay to avoid overwhelming the server
			});
		}
	);
}
