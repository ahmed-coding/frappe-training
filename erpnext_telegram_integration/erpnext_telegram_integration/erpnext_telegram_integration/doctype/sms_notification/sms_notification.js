// Copyright (c) 2019, Youssef Restom and contributors
// For license information, please see license.txt
// Copyright (c) 2018, Frappe Technologies and contributors
// For license information, please see license.txt


frappe.notification = {
	setup_fieldname_select: function(frm) {
		// get the doctype to update fields
		if(!frm.doc.document_type) {
			return;
		}

		frappe.model.with_doctype(frm.doc.document_type, function() {
			let get_select_options = function(df) {
				return {value: df.fieldname, label: df.fieldname + " (" + __(df.label) + ")"};
			}

			let get_date_change_options = function() {
				let date_options = $.map(fields, function(d) {
					return (d.fieldtype=="Date" || d.fieldtype=="Datetime")?
						get_select_options(d) : null;
				});
				// append creation and modified date to Date Change field
				return date_options.concat([
					{ value: "creation", label: `creation (${__('Created On')})` },
					{ value: "modified", label: `modified (${__('Last Modified Date')})` }
				]);
			}

			let fields = frappe.get_doc("DocType", frm.doc.document_type).fields;
			let options = $.map(fields,
				function(d) { return in_list(frappe.model.no_value_type, d.fieldtype) ?
					null : get_select_options(d); });

			// set value changed options
			frm.set_df_property("value_changed", "options", [""].concat(options));
			frm.set_df_property("set_property_after_alert", "options", [""].concat(options));

			// set date changed options
			frm.set_df_property("date_changed", "options", get_date_change_options());

		});
	}
}

frappe.ui.form.on('SMS Notification', {
	onload: function(frm) {
		frm.set_query("document_type", function() {
			return {
				"filters": {
					"istable": 0
				}
			}
		});
		frm.set_query("print_format", function() {
			return {
				"filters": {
					"doc_type": frm.doc.document_type
				}
			}
		});
		frm.toggle_reqd("recipients", !frm.doc.dynamic_recipients ? 1:0);
	},
	refresh: function(frm) {
		frappe.notification.setup_fieldname_select(frm);
		frm.get_field("is_standard").toggle(frappe.boot.developer_mode);
		frm.trigger('event');
	},

	document_type: function(frm) {
		frappe.notification.setup_fieldname_select(frm);
	},
	view_properties: function(frm) {
		frappe.route_options = {doc_type:frm.doc.document_type};
		frappe.set_route("Form", "Customize Form");
	},
	event: function(frm) {
		if(in_list(['Days Before', 'Days After'], frm.doc.event)) {
			frm.add_custom_button(__('Get Alerts for Today'), function() {
				frappe.call({
					method: 'erpnext_telegram_integration.erpnext_telegram_integration.doctype.sms_notification.sms_notification.get_documents_for_today',
					args: {
						notification: frm.doc.name
					},
					callback: function(r) {
						if(r.message) {
							frappe.msgprint(r.message);
						} else {
							frappe.msgprint(__('No alerts for today'));
						}
					}
				});
			});
		}
	},
	dynamic_recipients: function(frm) {
		frm.toggle_reqd("recipients", !frm.doc.dynamic_recipients ? 1:0);
	}
	
});
