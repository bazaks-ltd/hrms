<p>Dear Sir,</p>

<p>A new request titled <strong>"{{ doc.title or doc.name }}"</strong> has been submitted and is now pending your review and approval.</p>

<p>Please review the request at your earliest convenience.</p>

<hr />

<p><b>Request Summary:</b>
- Request Title: {{ doc.title or doc.name }}
- Submitted By: {{ doc.owner }}
- Department: {{ doc.department or "N/A" }}
- Submitted On: {{ frappe.format_date(doc.creation) }}</p>

<hr />

<p>You can review and take action on the request by clicking the link below:</p>

<p><a href="{{ frappe.utils.get_url() }}/app/{{ doc.doctype | lower | replace(" ", "-") }}/{{ doc.name }}">Review Request</a></p>

<p>Thank you.</p>
