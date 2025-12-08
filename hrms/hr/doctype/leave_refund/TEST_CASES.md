# Mauritius Leave Management System - Test Cases

## Overview
This document contains comprehensive test cases for the Mauritius Leave Management System implementation.

## Test Environment Setup

### Prerequisites
1. Create test employees with different joining dates:
   - Employee A: Joined < 6 months ago
   - Employee B: Joined 6-12 months ago
   - Employee C: Joined > 1 year ago
   - Employee D: 22 working days (5 days/week)
   - Employee E: 26 working days (6 days/week)

2. Create Leave Period for current year
3. Create Leave Policy with all leave types
4. Assign Leave Policy to test employees

---

## Test Case 1: First 6 Months Leave Types

### TC-1.1: Injury Unpaid Leave
**Objective:** Verify Injury Unpaid Leave can be applied for employees in first 6 months

**Steps:**
1. Login as Employee A (joined < 6 months ago)
2. Navigate to Leave Application
3. Select Leave Type: "Injury Unpaid Leave"
4. Enter from_date and to_date
5. Submit application

**Expected Result:**
- Application can be created
- Leave days exclude Sundays and holidays (if working_days = 22)
- No leave balance required (is_lwp = 1)

---

### TC-1.2: Injury Leave (14 days)
**Objective:** Verify Injury Leave allocation and application

**Steps:**
1. Create Leave Allocation for Employee A: 14 days of Injury Leave
2. Create Leave Application for Injury Leave (5 days)
3. Check leave balance

**Expected Result:**
- Allocation created successfully
- Balance shows 14 days allocated, 5 days taken, 9 days remaining
- Holidays excluded from leave days calculation

---

### TC-1.3: Training Leave (Paid) - 10 days
**Objective:** Verify Training Leave allocation when policy assigned

**Steps:**
1. Assign Leave Policy to Employee A (first time)
2. Check Leave Allocation for Training Leave (Paid)
3. Verify 10 days allocated

**Expected Result:**
- 10 days allocated once when policy is assigned
- Can apply for training leave
- Leave days exclude holidays

---

### TC-1.4: Unauthorized Leave (Unlimited)
**Objective:** Verify HR can allocate unlimited unauthorized leave

**Steps:**
1. Login as HR Manager
2. Create Leave Allocation for Employee A
3. Leave Type: "Unauthorized Leave"
4. Allocate 20 days (more than any limit)

**Expected Result:**
- Allocation succeeds (allow_over_allocation = 1, max_leaves_allowed = 0)
- Leave is LWP (is_lwp = 1)
- Sundays and holidays excluded

---

### TC-1.5: Compensatory Off (Unlimited)
**Objective:** Verify compensatory leave can be allocated unlimited

**Steps:**
1. Create Leave Allocation for Employee A
2. Leave Type: "Compensatory Off"
3. Allocate 15 days

**Expected Result:**
- Allocation succeeds
- Leave type is compensatory (is_compensatory = 1)
- Can be used for leave applications

---

## Test Case 2: 6 Months from Joining Date

### TC-2.1: Monthly Sick Leave (Earned Leave)
**Objective:** Verify monthly sick leave allocation via scheduler

**Steps:**
1. Assign Leave Policy to Employee B (joined 6-12 months ago)
2. Verify Monthly Sick Leave in policy (6 days annual, monthly frequency)
3. Run scheduler: `bench execute hrms.hr.utils.allocate_earned_leaves`
4. Check Leave Allocation after 1 month

**Expected Result:**
- 0.5 days allocated per month (6 days / 12 months)
- Allocation increases monthly via scheduler
- Maximum 6 days per year
- applicable_after = 180 days (6 months)

---

### TC-2.2: Monthly Local Leave (Earned Leave)
**Objective:** Verify monthly local leave allocation

**Steps:**
1. Same as TC-2.1 but for Monthly Local Leave
2. Verify monthly allocation
3. Apply for leave using monthly local leave

**Expected Result:**
- 0.5 days allocated per month
- Can apply for leave
- Maximum 6 days per year

---

### TC-2.3: Tenure Validation - Monthly Leaves
**Objective:** Verify employees < 6 months cannot apply for monthly leaves

**Steps:**
1. Login as Employee A (< 6 months)
2. Try to create Leave Application
3. Select "Monthly Sick Leave"

**Expected Result:**
- Error message: "Monthly Sick Leave is applicable after 180 working days (6 months from joining date)"
- Application cannot be submitted

---

## Test Case 3: 1 Year from Joining Date

### TC-3.1: Vacation Leave (30 days, Encashable)
**Objective:** Verify vacation leave allocation and encashment

**Steps:**
1. Assign Leave Policy to Employee C (> 1 year)
2. Verify Vacation Leave allocation (30 days)
3. Apply for 10 days vacation leave
4. Create Leave Encashment for remaining 20 days

**Expected Result:**
- 30 days allocated
- 10 days taken, 20 days remaining
- Encashment creates Additional Salary entry
- Leave balance reduced by encashed days
- applicable_after = 365 days

---

### TC-3.2: Sick Leave (15 days, Carry Forward)
**Objective:** Verify sick leave with carry forward

**Steps:**
1. Allocate 15 days Sick Leave to Employee C
2. Apply for 5 days
3. At end of leave period, verify carry forward
4. Check new period allocation includes carry forward

**Expected Result:**
- 15 days allocated
- 5 days taken, 10 days remaining
- Carry forward works (is_carry_forward = 1)
- Unused leaves carry to next period

---

### TC-3.3: Maternity Leave (112 days)
**Objective:** Verify maternity leave allocation

**Steps:**
1. Allocate Maternity Leave to Employee C
2. Apply for 112 days maternity leave
3. Verify application

**Expected Result:**
- 112 days allocated
- Can apply for full 112 days
- applicable_after = 365 days

---

### TC-3.4: Paternity Leave (28 days)
**Objective:** Verify paternity leave

**Steps:**
1. Allocate Paternity Leave to Employee C
2. Apply for 28 days

**Expected Result:**
- 28 days allocated
- Application successful
- applicable_after = 365 days

---

### TC-3.5: Local Leave (Merged, Encashable)
**Objective:** Verify merged Local Leave functionality

**Steps:**
1. Verify "Local Leave" exists (not "Local Leave Er" or "Local Leave Ee")
2. Allocate 11 days Local Leave to Employee C
3. Apply for 5 days
4. Create Leave Encashment for 6 days

**Expected Result:**
- Only "Local Leave" exists in system
- 11 days allocated
- Encashment works (allow_encashment = 1)
- applicable_after = 365 days

---

### TC-3.6: Special Leave (Unlimited)
**Objective:** Verify HR can allocate unlimited special leave

**Steps:**
1. HR creates Leave Allocation
2. Leave Type: "Special Leave"
3. Allocate 25 days

**Expected Result:**
- Allocation succeeds (allow_over_allocation = 1)
- No maximum limit enforced
- applicable_after = 365 days

---

### TC-3.7: Wedding Leave (6 days)
**Objective:** Verify wedding leave

**Steps:**
1. Allocate Wedding Leave to Employee C
2. Apply for 6 days

**Expected Result:**
- 6 days allocated
- Can apply for wedding leave
- applicable_after = 365 days

---

### TC-3.8: Compassionate Leave (3 days)
**Objective:** Verify compassionate leave

**Steps:**
1. Allocate Compassionate Leave to Employee C
2. Apply for 3 days

**Expected Result:**
- 3 days allocated
- Application successful
- applicable_after = 365 days

---

## Test Case 4: LWP Sunday & Holiday Exclusion

### TC-4.1: LWP with 22 Working Days (5 days/week)
**Objective:** Verify Sundays excluded for 5-day workweek employees

**Steps:**
1. Set Employee D working_days = 22
2. Create Leave Application
3. Leave Type: "Leave Without Pay"
4. From: Monday, To: Next Monday (8 calendar days, includes 1 Sunday)
5. Check total_leave_days

**Expected Result:**
- total_leave_days = 7 (8 days - 1 Sunday)
- Sunday excluded from calculation
- Holidays also excluded

---

### TC-4.2: LWP with 26 Working Days (6 days/week)
**Objective:** Verify Sundays NOT excluded for 6-day workweek employees

**Steps:**
1. Set Employee E working_days = 26
2. Create Leave Application
3. Leave Type: "Leave Without Pay"
4. From: Monday, To: Next Monday (8 calendar days, includes 1 Sunday)
5. Check total_leave_days

**Expected Result:**
- total_leave_days = 7 (8 days - 1 holiday, Sunday included)
- Sunday NOT excluded (working day)
- Only holidays excluded

---

### TC-4.3: LWP with Holidays
**Objective:** Verify holidays excluded for all LWP types

**Steps:**
1. Create Holiday List with holiday on Wednesday
2. Create Leave Application for Employee D
3. Leave Type: "Unpaid Local Leave"
4. From: Monday, To: Friday (includes holiday on Wednesday)
5. Check total_leave_days

**Expected Result:**
- total_leave_days = 4 (5 days - 1 holiday)
- Holiday excluded
- Sunday also excluded (if working_days = 22)

---

### TC-4.4: Non-LWP Leave with Holidays
**Objective:** Verify holidays excluded for regular leaves too

**Steps:**
1. Create Leave Application for Employee C
2. Leave Type: "Vacation Leave"
3. From: Monday, To: Friday (includes holiday)
4. Check total_leave_days

**Expected Result:**
- total_leave_days = 4 (holiday excluded)
- include_holiday = 0 for all leave types

---

## Test Case 5: Leave Refund

### TC-5.1: Create Leave Refund
**Objective:** Verify leave refund creates Additional Salary and updates balance

**Steps:**
1. Employee C has 10 days Local Leave allocated, 5 days taken
2. HR creates Leave Refund
3. Employee: Employee C
4. Leave Type: "Local Leave"
5. Refund Days: 3
6. Salary Component: "Leave Refund" (or custom)
7. Submit Leave Refund

**Expected Result:**
- Additional Salary created and submitted
- Leave Allocation balance increases by 3 days (from 5 to 8 remaining)
- Leave Ledger Entry created (positive entry)
- Refund amount calculated based on daily rate

---

### TC-5.2: Leave Refund Amount Calculation
**Objective:** Verify refund amount calculation

**Steps:**
1. Create Leave Refund for Employee C
2. Refund Days: 5
3. Check refund_amount calculation

**Expected Result:**
- Uses leave_encashment_amount_per_day from Salary Structure if available
- Otherwise calculates: (Basic Salary / working_days) * refund_days
- Currency set correctly

---

### TC-5.3: Cancel Leave Refund
**Objective:** Verify canceling refund reverses changes

**Steps:**
1. Create and submit Leave Refund (3 days)
2. Cancel the Leave Refund
3. Check Leave Allocation balance
4. Check Additional Salary status

**Expected Result:**
- Additional Salary canceled
- Leave Allocation balance reverted (decreased by 3 days)
- Leave Ledger Entry reversed

---

### TC-5.4: Leave Refund with Payroll Entry Link
**Objective:** Verify payroll entry can be linked

**Steps:**
1. Create Payroll Entry
2. Create Leave Refund
3. Link Payroll Entry field
4. Submit both

**Expected Result:**
- Payroll Entry linked successfully
- Refund processed in payroll

---

## Test Case 6: Leave Encashment

### TC-6.1: Vacation Leave Encashment
**Objective:** Verify vacation leave encashment

**Steps:**
1. Employee C has 20 days Vacation Leave balance
2. Create Leave Encashment
3. Leave Type: "Vacation Leave"
4. Encashment Days: 10
5. Submit

**Expected Result:**
- Additional Salary created with "Leave Encashment" component
- Leave balance reduced by 10 days
- Leave Ledger Entry created (negative entry)
- Encashment amount calculated correctly

---

### TC-6.2: Local Leave Encashment
**Objective:** Verify local leave encashment

**Steps:**
1. Employee C has 8 days Local Leave balance
2. Create Leave Encashment for 5 days
3. Submit

**Expected Result:**
- Encashment successful
- Balance reduced to 3 days
- Additional Salary created

---

## Test Case 7: Tenure-Based Validation

### TC-7.1: Employee < 6 Months - Restricted Leaves
**Objective:** Verify employees < 6 months cannot apply for restricted leaves

**Test Leaves (should FAIL for Employee A):**
- Monthly Sick Leave (applicable_after = 180)
- Monthly Local Leave (applicable_after = 180)
- Vacation Leave (applicable_after = 365)
- Sick Leave (applicable_after = 365)
- All 1-year leaves

**Expected Result:**
- Error: "{Leave Type} is applicable after 180/365 working days (6 months/1 year from joining date)"
- Application cannot be submitted

---

### TC-7.2: Employee 6-12 Months - Partial Access
**Objective:** Verify employees 6-12 months can access monthly leaves only

**Test Leaves for Employee B:**
- Monthly Sick Leave: ✅ Allowed
- Monthly Local Leave: ✅ Allowed
- Vacation Leave: ❌ Not allowed (applicable_after = 365)
- Sick Leave: ❌ Not allowed

**Expected Result:**
- Monthly leaves work
- 1-year leaves show error

---

### TC-7.3: Employee > 1 Year - Full Access
**Objective:** Verify employees > 1 year can access all leaves

**Test Leaves for Employee C:**
- All leave types: ✅ Allowed

**Expected Result:**
- All leave applications successful
- No tenure errors

---

## Test Case 8: Local Leave Merge

### TC-8.1: Verify Old Types Removed
**Objective:** Verify Local Leave Er and Ee are deleted

**Steps:**
1. Check Leave Type list
2. Search for "Local Leave Er"
3. Search for "Local Leave Ee"
4. Search for "Local Leave"

**Expected Result:**
- "Local Leave Er" does not exist
- "Local Leave Ee" does not exist
- "Local Leave" exists

---

### TC-8.2: Verify Allocations Merged
**Objective:** Verify old allocations updated to Local Leave

**Steps:**
1. Check Leave Allocations
2. Filter by old leave types
3. Filter by "Local Leave"

**Expected Result:**
- No allocations with old leave types
- All allocations show "Local Leave"
- Balances preserved

---

### TC-8.3: Verify Applications Updated
**Objective:** Verify leave applications reference new type

**Steps:**
1. Check Leave Applications
2. Filter by old leave types
3. Filter by "Local Leave"

**Expected Result:**
- No applications with old leave types
- All applications show "Local Leave"

---

### TC-8.4: Verify Ledger Entries Updated
**Objective:** Verify ledger entries updated

**Steps:**
1. Check Leave Ledger Entries
2. Filter by old leave types

**Expected Result:**
- All ledger entries show "Local Leave"
- Transaction history preserved

---

## Test Case 9: Leave Policy Assignment

### TC-9.1: Assign Policy Based on Joining Date
**Objective:** Verify policy assignment works for all employees

**Steps:**
1. Create Leave Policy with all leave types
2. Assign to Employee A (assignment_based_on = "Joining Date")
3. Assign to Employee B
4. Assign to Employee C
5. Check allocations created

**Expected Result:**
- Policy assigned successfully
- Allocations created based on tenure
- Training Leave allocated once (10 days)
- Monthly leaves allocated based on months passed

---

### TC-9.2: Single Policy for All Employees
**Objective:** Verify one policy works for all tenure stages

**Steps:**
1. Create one Leave Policy
2. Add all leave types with appropriate allocations
3. Assign to employees with different tenures
4. Verify each employee gets correct allocations

**Expected Result:**
- One policy works for all
- Each employee gets leaves based on tenure
- applicable_after field enforces restrictions

---

## Test Case 10: Edge Cases

### TC-10.1: Half Day Leave
**Objective:** Verify half day leave calculation

**Steps:**
1. Create Leave Application
2. Check half_day checkbox
3. Set half_day_date
4. Check total_leave_days

**Expected Result:**
- Half day calculated as 0.5 days
- Holidays and Sundays still excluded correctly

---

### TC-10.2: Leave Across Allocation Period
**Objective:** Verify leave spanning multiple periods

**Steps:**
1. Create Leave Application
2. From date in Period 1, To date in Period 2
3. Submit

**Expected Result:**
- Handled correctly by system
- Uses appropriate allocations

---

### TC-10.3: Negative Leave Balance
**Objective:** Verify negative balance handling

**Steps:**
1. Employee has 5 days balance
2. Apply for 7 days (if allow_negative = 1)

**Expected Result:**
- Behavior depends on allow_negative setting
- Most leave types don't allow negative

---

## Test Execution Checklist

- [ ] TC-1.1: Injury Unpaid Leave
- [ ] TC-1.2: Injury Leave (14 days)
- [ ] TC-1.3: Training Leave (Paid)
- [ ] TC-1.4: Unauthorized Leave
- [ ] TC-1.5: Compensatory Off
- [ ] TC-2.1: Monthly Sick Leave
- [ ] TC-2.2: Monthly Local Leave
- [ ] TC-2.3: Tenure Validation - Monthly Leaves
- [ ] TC-3.1: Vacation Leave Encashment
- [ ] TC-3.2: Sick Leave Carry Forward
- [ ] TC-3.3: Maternity Leave
- [ ] TC-3.4: Paternity Leave
- [ ] TC-3.5: Local Leave (Merged)
- [ ] TC-3.6: Special Leave
- [ ] TC-3.7: Wedding Leave
- [ ] TC-3.8: Compassionate Leave
- [ ] TC-4.1: LWP with 22 Working Days
- [ ] TC-4.2: LWP with 26 Working Days
- [ ] TC-4.3: LWP with Holidays
- [ ] TC-4.4: Non-LWP with Holidays
- [ ] TC-5.1: Create Leave Refund
- [ ] TC-5.2: Refund Amount Calculation
- [ ] TC-5.3: Cancel Leave Refund
- [ ] TC-5.4: Refund with Payroll Entry
- [ ] TC-6.1: Vacation Leave Encashment
- [ ] TC-6.2: Local Leave Encashment
- [ ] TC-7.1: Employee < 6 Months Validation
- [ ] TC-7.2: Employee 6-12 Months Validation
- [ ] TC-7.3: Employee > 1 Year Validation
- [ ] TC-8.1: Old Types Removed
- [ ] TC-8.2: Allocations Merged
- [ ] TC-8.3: Applications Updated
- [ ] TC-8.4: Ledger Entries Updated
- [ ] TC-9.1: Policy Assignment
- [ ] TC-9.2: Single Policy for All
- [ ] TC-10.1: Half Day Leave
- [ ] TC-10.2: Leave Across Periods
- [ ] TC-10.3: Negative Balance

---

## Notes

1. **Test Data Setup:**
   - Create test employees with different joining dates
   - Set up holiday lists with test holidays
   - Create salary structures with leave_encashment_amount_per_day

2. **Scheduler Testing:**
   - Monthly earned leaves require scheduler to run
   - Use: `bench execute hrms.hr.utils.allocate_earned_leaves`

3. **Working Days:**
   - Test with both 22 and 26 working days
   - Verify Sunday exclusion logic

4. **Leave Periods:**
   - Ensure Leave Periods are set up correctly
   - Test with current and future periods

5. **Permissions:**
   - Test with HR Manager role
   - Test with Employee role
   - Verify appropriate access controls

