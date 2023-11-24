// Copyright (c) 2023, Ahmed-Coding and contributors
// For license information, please see license.txt

frappe.ui.form.on("DocType Test 1", {
	refresh(frm) {
        frappe.msgprint('A row has been added to the DocType Test 1  table 🎉 ');

	},
	// onload(frm) {
    //     frappe.msgprint('A row has been added to the DocType Test 1  table 🎉 ');

    // },
    // refresh(frm)
});
