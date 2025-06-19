frappe.ui.form.on('Employee Letter', {
    refresh: function(frm) {
        // Add custom buttons
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__('Preview Letter'), function() {
                preview_letter(frm);
            });
            
            frm.add_custom_button(__('Generate Content'), function() {
                generate_content(frm);
            });
        }
        
        if (frm.doc.generated_content && frm.doc.docstatus === 1) {
            frm.add_custom_button(__('Print Letter'), function() {
                print_letter(frm);
            });
            
            frm.add_custom_button(__('Email Letter'), function() {
                email_letter(frm);
            });
        }
    },
    
    letter_template: function(frm) {
        if (frm.doc.letter_template && frm.doc.employee) {
            generate_content(frm);
        }
    },
    
    employee: function(frm) {
        if (frm.doc.letter_template && frm.doc.employee) {
            generate_content(frm);
        }
    }
});

function generate_content(frm) {
    frm.call('get_formatted_content').then(r => {
        if (r.message) {
            frm.set_value('rendered_content', r.message);
        }
    });
}

function preview_letter(frm) {
    if (!frm.doc.rendered_content) {
        frappe.msgprint(__('Please generate content first'));
        return;
    }
    
    frappe.utils.print(
        frm.doc.doctype,
        frm.doc.name,
        'Employee Letter Format'
    );
}

function print_letter(frm) {
    window.print();
}

function email_letter(frm) {
    frappe.call({
        method: 'frappe.core.doctype.communication.email.make',
        args: {
            recipients: frm.doc.employee,
            subject: `Letter - ${frm.doc.reference_number}`,
            content: 'Please find attached your letter.',
            doctype: frm.doc.doctype,
            name: frm.doc.name,
            print_format: 'Employee Letter Format'
        }
    });
}