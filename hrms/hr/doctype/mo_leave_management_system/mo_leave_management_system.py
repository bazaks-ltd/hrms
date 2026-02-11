# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MOLeaveManagementSystem(Document):
	def onload(self):
		# lightweight help text for admins
		self.help_text = frappe.render_template(
			"""
<div>
  <p><strong>Purpose</strong>: this Single DocType is the source of truth for MO leave allocation rules/toggles.</p>
  <ul>
    <li><strong>Allocate MO Leaves</strong> (Control Panel): used by HR for new joiners and yearly allocations. It is idempotent (won't override existing allocations).</li>
    <li><strong>Daily Weekday Allocator</strong>: if enabled, it only processes employees missing allocations who have crossed 6 months / 1 year thresholds.</li>
  </ul>
</div>
			"""
		)

