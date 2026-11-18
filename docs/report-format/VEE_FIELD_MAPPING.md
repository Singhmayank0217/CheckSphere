# VEE FORMAT: field mapping (red = mandatory, black = optional)

Master reference: the owner's `VEE FORMAT (1).docx`. Owner's rule (14-Nov-2026): **red content = mandatory**, **black content = optional**. Both are printed in their original colour, font, size, bold/underline, table position and order. This replaces the earlier red-only interpretation. Layout code: `backend/vee_report.py`. Form fields: `backend/report_config.py`.

**How to read the tables**

| Term | Meaning |
|---|---|
| **R** / **K** | Red / black in the master. |
| *existing* | The key already existed in CheckSphere before this change. |
| *new* | An optional field added now. |
| *case* | Taken from the case record. |
| *call log* | Taken from the telephone call log. |
| *auto* | Set by the server. |
| *static* | Fixed text from the master. |
| "Required now" | Whether submission is blocked when the field is empty. |

A black value that was not entered prints `N/A`.

## 1. Applicant / Co-Applicant Residence Verification Report (`residence_applicant`, `residence_coapplicant`)

| VEE label | Colour | Required now | CheckSphere field | In DB before? |
|---|---|---|---|---|
| Report title, "The following information should be obtained…" | K | static | static | n/a |
| Bank / Branch Name | R | yes | case `client_name` / `branch_name` | yes (case) |
| Name of Applicant | R | yes | `applicant_name` | yes |
| Present Residence Address | R | yes | `observed_address` (falls back to case address) | yes |
| Date of Visit / Time of Visit | R | auto | `visit_datetime` (server) | yes |
| DOB | R | yes | `applicant_dob` (date picker) | yes |
| Address Confirmed | R | yes | `address_outcome` | yes |
| Address Confirmed by | R | yes | `address_confirmed_by` | yes |
| Person Met / Relationship | R | yes | `person_met` / `relationship` | yes |
| Marital Status | R | yes | `marital_status` | yes |
| Nearest Landmark | R | **yes (was optional)** | `landmark` | yes |
| No of Residents in house | R | **yes (was optional)** | `residents_count` | yes |
| Years at current residence | R | **yes (was optional)** | `years_at_residence` | yes |
| No of Earning Family Members | R | yes | `earning_members` | yes |
| Residence Status | R | yes | `residence_status` | yes |
| Approx. Value (If Owned) | K | **no (was mandatory)** | `approx_value` | yes |
| Approx. Rent | K | **no (was mandatory)** | `approx_rent` | yes |
| Unit / Type of Roof / Vehicle | R | yes | `unit` / `roof_type` / `vehicle` | yes |
| Type of Loan | R | yes | `loan_type`, pre-filled from case `loan_type`, editable | *new* form field (case had it) |
| "Verifier Observation." heading | K | static | static | n/a |
| Location | K | no | `accessibility` | yes |
| Locality | K | **no (was mandatory)** | `locality` | yes |
| Accommodation Type | K | no | `accommodation_type` | *new* |
| Interior Condition | K | no | `interior_condition` | *new* |
| Standard Living | K | no | `standard_of_living` | *new* |
| Approx. Area (sq. ft.) | K | no | `approx_area_sqft` | *new* |
| Assets Seen (Y/N) | R | yes | `assets_seen` | yes |
| "If the house is locked…" heading | K | static | static | n/a |
| Applicant Name / Person Met / Relationship (locked house) | K | no | `nb_applicant_name` / `nb_person_met` / `nb_relationship` | *new* |
| Applicant Age (Approx.) / No of Residents in House | K | no | `nb_applicant_age` / `nb_residents` | *new* |
| Year Lived at this Residence / Occupation | K | no | `nb_years_lived` / `nb_occupation` | *new* |
| "Verifier Remarks:-" heading | K | static | static | n/a |
| Verifier Remarks text box | R | **yes (was optional)** | `agent_remarks` | yes |
| Remarks | R | yes | `vee_remarks` (Positive / Negative) | yes |
| Did the Customer Applied Previously | K | no | `previously_applied` | *new* |
| Date of Previous File | K | no | `previous_file_date` | *new* |
| Recommendation | R | yes | `vee_recommendation` (Yes / No) | yes |
| "N/A" cell beside Recommendation | K | static | static | n/a |
| Reasons for Not Recommended (please tick), reasons 1–10 | K | no | `not_recommended_reasons` (tick list) | *new* |
| Verifier Name / Authorized Signature with Seal | K | auto | `agent_name` | yes |

## 2. Office Verification Report (`office_coapplicant`, `business_applicant`)

| VEE label | Colour | Required now | CheckSphere field | In DB before? |
|---|---|---|---|---|
| Title, "The following information… in the office." | K | static | static | n/a |
| Branch Name / Name of Applicant | R | yes | case `branch_name` / `applicant_name` | yes |
| Name of Employer | R | yes | `employer_name` | yes |
| Office Address | R | yes | `observed_address` | yes |
| PH No / DOB | R | yes | `office_phone` / `applicant_dob` | yes |
| Date / Time of Visit | R | auto | `visit_datetime` | yes |
| Person Met | R | yes | `person_met` | yes |
| Designation (of person met) | R | **yes (was optional)** | `person_designation` | yes |
| Designation of Applicant | R | **yes (was optional)** | `applicant_designation` | yes |
| No of Years Worked Here | R | **yes (was optional)** | `years_employed` | yes |
| Previous Employment | K | no | `previous_employment` | *new* |
| Year of establishment | K | no | `year_of_establishment` | *new* |
| Office Board Present? | K | **no (was mandatory)** | `board_present` | yes |
| Terms of Employment / Type of Employer Co. / Nature of Business | R | yes | `employment_terms` / `employer_type` / `nature_of_business` | yes |
| Approx. Area of the Office | K | no | `office_area_sqft` | *new* |
| No. of Employees / No. of Branch / Office | K | no | `employees_count` / `branches_count` | *new* |
| Premises | K | no | `premises_type` | yes |
| Assets Seen? (Y/N) | K | no | `office_assets_seen` | *new* |
| "Comments:-", Accessibility of the Office with Direction | K | no | `accessibility` | yes |
| Neighbor's Feedback | K | no | `neighbour_feedback` | *new* |
| Verifier Remarks | R | **yes (was optional)** | `agent_remarks` | yes |
| Remarks / Recommendation | R | yes | `vee_remarks` / `vee_recommendation` | yes |
| Did the Customer Applied Previously? / Date of Previous File | K | no | `previously_applied` / `previous_file_date` | *new* |
| Reasons for Not Recommended (please Tick) | K | no | `not_recommended_reasons` | *new* |
| Verifier Name / Authorized Signature with Seal | K | auto | `agent_name` | yes |

CheckSphere-only mandatory fields that are not printed in VEE are unchanged: `relationship_to_business`, `business_operational`, `exterior_observation`.

## 3. Residence Tele Verification Report (`tel_residence`)

| VEE label | Colour | Required now | CheckSphere field | In DB before? |
|---|---|---|---|---|
| Name of Applicant / Name of the Co-Applicant | K | no | `applicant_name` / case `co_applicant_name` | yes |
| Date of Birth | K | no | `applicant_dob` | *new* for this type |
| Residence Address of the Applicant | K | no | case `assigned_address` | yes (case) |
| Permanent Address of the Applicant | K | no | `permanent_address` | *new* |
| Contact No (Telephone / Mobile No) | K | auto | call log `phone_number`, else case `primary_phone` | yes |
| Person Spoken To / Relationship / Address Confirmed? | K | auto | latest *Confirmed* call: `person_met` / `relationship` / `info_confirmed` | yes (call log) |
| Reference Tele Number / Person Spoken / Confirmed | K | no | `ref_tele_number` / `ref_person_spoken` / `ref_confirmed` | *new* |
| Attempt 1st–4th, Outcome (C / B / Cl / Nr) | K | auto | call log `result` | yes |
| Date of Calling / Time of Calling | R | yes (minimum 3 call attempts) | call log `attempt_at` | yes |
| Outcome legend, Tele Verification Result | K | no | static / `tele_result` | *new* |
| Verifier Name / Signature | K | auto | `agent_name` | yes |

## 4. Office Tele Verification Report (`tel_office`)

| VEE label | Colour | Required now | CheckSphere field | In DB before? |
|---|---|---|---|---|
| Name of Applicant | K | no | `applicant_name` | yes |
| Employer Name & Address | K | no | `employer_name_address` | *new* |
| Designation of the Applicant | K | no | `applicant_designation` | *new* for this type |
| Nature of Business / Office | K | no | `nature_of_business` | *new* for this type |
| No of Years at Present Employment | K | no | `years_at_employment` | *new* |
| Office Contactable Number | K | auto | call log `phone_number`, else case `primary_phone` | yes |
| Person Spoken To / Address of the Office Confirmed? | K | auto | call log `person_met` / `info_confirmed` | yes |
| Designation (of person spoken to) | K | no | `spoken_designation` | *new* |
| Tele calling Log, Date / Time of Calling | R | yes (minimum 3 call attempts) | call log | yes |
| Outcome, legend, Tele Verification Result, Verifier | K | auto / no | call log / `tele_result` / `agent_name` | partly *new* |

## 5. KYC Verification Report (`kyc`): all black in VEE

| VEE label | Required now | CheckSphere field | In DB before? |
|---|---|---|---|
| Row 1: Name, Pan Card No., Remarks, Voter Card No., Remarks, Aadhar Card No., Remarks | yes (owner decision 3, Task 2) | `applicant_name`, `kyc_pan_no`, `kyc_remarks_1`, `kyc_voter_no`, `kyc_remarks_2`, `kyc_aadhaar_no`, `kyc_remarks_3` | yes |
| Row 2 (second person / co-applicant) | no | `kyc2_name` (pre-filled with the co-applicant), `kyc2_pan_no`, `kyc2_remarks_1`, `kyc2_voter_no`, `kyc2_remarks_2`, `kyc2_aadhaar_no`, `kyc2_remarks_3` | *new* |
| Verifier Name / Signature | auto | `verifier_name` | yes |

**Needs your decision:** by the colour rule, every KYC field is black (optional). The earlier owner decision made row 1 mandatory, and that is kept. Please confirm.

## 6. G.S.T. Verification Report (`gst`): all black in VEE

| VEE label | Required now | CheckSphere field | In DB before? |
|---|---|---|---|
| Date / Time of Visit | auto | `verification_datetime` | yes |
| Name of the applicant, Business Name, Business Address, Registration no., Designation, Assessment year | yes (earlier owner decision) | `applicant_name`, `business_name`, `business_address`, `gst_registration_no`, `applicant_designation`, `assessment_year` | yes |
| Status / Remarks | yes | `gst_status` / `factual_remarks` | yes |
| Verifier Name / Signature | auto | `verifier_name` | yes |

**Needs your decision:** these fields are black but were made mandatory earlier. They stay mandatory until you say otherwise.

## 7. Formats in the master with no matching CheckSphere form (not implemented; your decision is needed)

| VEE section | Labels | CheckSphere today | What is missing |
|---|---|---|---|
| Other Bank A/c Verification Report | Date/Time of Visit, Name, Bank Name, Branch Name, Account No, Statement period, Bank Statement confirmed by, Status, Remarks | `bank_account` uses the generic document form (`document_type`, `document_period`, `document_ref_no`, `outcome`, `factual_remarks`) | `bank_name`, `bank_branch`, `account_no` (masked), `statement_period`, `confirmed_by`, `status`. The mapping is not 1:1, so it is not guessed. |
| Salary Slip Verification Report | Date/Time, Name, Office Name, Office Address, Designation, Net salary per month (9 months), Status, Remarks | `income`, generic document form | which income document (Salary Slip / Form 16 / ITR), `office_name`, `office_address`, monthly net salary rows |
| Form 16 Verification Report | Date/Time, Name, Office Name, Address, Designation, Assessment year, Status, Remarks | `income` | as above, plus `assessment_year` |
| ITR Verification Report | Assessment Year, Name of the assessee, Ward/Circle/Range, Gross Total Income, Acknowledgement Number, Date of Filing, PAN, Date of Visit, Result, Comments ("Ack No" and the assessment year are red) | `income` | all of these fields, plus which red items are mandatory |
| Residence / Office verification photo pages | "<NAME> RESIDENCE / OFFICE VERIFICATION PHOTO", Verifier Name, Signature | implemented: the case's own five photographs plus a signature block | — |

Until these are decided, `income`, `bank_account`, `seller` and `custom` keep the standard CheckSphere layout, without the evidence reference table.
