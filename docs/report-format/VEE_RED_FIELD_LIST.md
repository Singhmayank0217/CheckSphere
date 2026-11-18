# VEE FORMAT: red-coloured content, by verification type

> **Superseded on 14-Nov-2026 (after the Android test):** the owner corrected the rule. Exports must contain **both** the
> red content (mandatory fields) and the black content (optional fields) of the master. The current mapping is in
> [VEE_FIELD_MAPPING.md](VEE_FIELD_MAPPING.md). This file is kept as the record of the earlier decisions 1–7.

## Decisions taken on 14-Nov-2026 (business owner)

1. **KYC and GST:** these formats have no red in VEE, so they use their own VEE labels, styled like the red content.
   A new **GST Verification** request type was added (report type `gst`).
2. **Titles:** the black VEE report title of each format is kept, as are the photo-page titles.
3. **Missing fields:** red fields that the forms didn't capture were **added to the agent form as mandatory fields**.
   Agents enter "N/A" where something does not apply.
   - Residence (applicant / co-applicant): `applicant_dob`, `address_confirmed_by`, `marital_status`,
     `earning_members`, `approx_value`, `approx_rent`, `unit`, `roof_type`, `vehicle`, `assets_seen`,
     `vee_remarks`, `vee_recommendation`
   - Office / Business: `applicant_dob`, `office_phone`, `employment_terms`, `employer_type`, `vee_remarks`,
     `vee_recommendation`
   - KYC: `kyc_pan_no`, `kyc_remarks_1`, `kyc_voter_no`, `kyc_remarks_2`, `kyc_aadhaar_no`, `kyc_remarks_3`
   - GST: `business_name`, `business_address`, `gst_registration_no`, `applicant_designation`, `assessment_year`,
     `gst_status`, `factual_remarks`, `verifier_name`
4. **Approx. Value (If Owned)** and **Approx. Rent** are included in the residence report, although they are black in VEE.

5. **Live since 14-Nov-2026:** Word and PDF exports of every type listed in `vee_report.TITLES` use this format.
   Income, bank account, seller and custom types have no VEE format and keep the standard CheckSphere layout.
6. **Photos:** the "Evidence Photo References" table (slot, file name, time, GPS) is removed from all exports.
   The case's own stored, watermarked photographs are embedded byte-for-byte, each under its category label
   (Exterior – Front, Exterior – Second Angle, Interior, Selfie, Supporting Document). A missing or unreadable photo
   shows a missing-evidence notice; nothing is ever substituted.
7. **DOB** is picked with a date picker and stored as `YYYY-MM-DD`. It is printed as `DD-MMM-YYYY`, and older
   free-text values are printed exactly as stored.

The generator is `backend/vee_report.py`. Samples are in `docs/report-format/samples/` and are produced by
`backend/tests/make_vee_samples.py`.

Source: `VEE FORMAT (1).docx`, as supplied on 14-Nov-2026. Every run's colour was read directly from the document XML.
The only red used is pure red **`FF0000`**: 200 colour tags, 141 of them on visible text. Everything else is black
(`000000` or automatic). No red comes from highlights, shading or styles.

All sample values in red (DAS, RACPC NAYAPALI, SELF, MARRIED, POSITIVE, …) are examples. They will be replaced by
the case's own data, or left blank / N/A.

Formatting of the red content in the source:

- **Residence:** Book Antiqua 9 pt. Labels are regular and values are **bold**. Bordered table grid, 6 columns.
- **Office:** Book Antiqua 10 pt labels, values **bold** (9–10 pt). Bordered table grid.
- **Telephone:** Book Antiqua 10 pt **bold**.
- **ITR:** Cambria 12 pt, partly bold.

Column "CheckSphere source" shows where the value would come from. **Not captured** means the verification form has
no such field today, so the field would print blank unless a field is added to the form.

---

## 1. Applicant Residence Verification Report (Co-Applicant Residence is identical)

| # | Red label (as in VEE) | Position in VEE table | CheckSphere source |
|---|---|---|---|
| 1 | Bank / Branch Name | row 1, full width | Case: Client name / Branch name |
| 2 | Name of Applicant | row 2, full width | Case / form: Applicant Name (Co-applicant Name on the co-applicant form) |
| 3 | Present Residence Address | row 3, full width | Form: Observed Address (falls back to the assigned address) |
| 4 | Date of Visit | row 4, left third | Form: Date & Time of Visit (automatic), date part |
| 5 | Time of Visit | row 4, middle third | Same, time part |
| 6 | DOB | row 4, right third | **Not captured** |
| 7 | Address Confirmed | row 5, left half | Form: Address Outcome (Confirmed → YES, Not Confirmed → NO, Inconclusive → INCONCLUSIVE) |
| 8 | Address Confirmed by | row 5, right half | **Not captured** (closest: Person Met + Relationship) |
| 9 | Person Met | row 6, left half | Form: Person Met |
| 10 | Relationship | row 6, right half | Form: Relationship with Applicant |
| 11 | Marital Status | row 7, left half | **Not captured** |
| 12 | Nearest Landmark | row 7, right half | Form: Landmark |
| 13 | No of Residents in house | row 8, left | Form: Number of Residents |
| 14 | Years at current residence | row 8, middle | Form: Years at Residence |
| 15 | No of Earning Family Members | row 8, right | **Not captured** |
| 16 | Residence Status | row 9, left | Form: Residence Status |
| 17 | Unit | row 10, left half | **Not captured** |
| 18 | Type of Roof | row 10, right half | **Not captured** |
| 19 | Vehicle | row 11, left half | **Not captured** |
| 20 | Type of Loan | row 11, right half | Case: Loan / Product type |
| 21 | Assets Seen (Y/N) | own row, full width | **Not captured** |
| 22 | Verifier Remarks (red narrative box, no label of its own) | single-cell box | Form: Agent Remarks |
| 23 | Remarks (sample "POSITIVE") | row, full width | **Not captured** as a field (see question C) |
| 24 | Recommendation (sample "YES") | row, left half | **Not captured** |

**Black in this section and therefore excluded:** the title, the instruction line, Approx. Value (If Owned),
Approx. Rent, the whole Verifier Observation table (Location, Locality, Accommodation, Interior, Standard of Living,
Area) except Assets Seen, the "house locked" neighbour table, Previously Applied / Date of Previous File, the
Reasons-for-Not-Recommended tick table, Verifier Name and Authorized Signature.

> Note: your message listed *Property Value or Rent* as an example. In this document **Approx. Value** and
> **Approx. Rent** are black, so a strict red-only rule excludes them. Also, *Locality* has red formatting only on an
> empty paragraph mark, while its text is black, so it is excluded too.

## 2. Office Verification Report

| # | Red label | Position | CheckSphere source |
|---|---|---|---|
| 1 | Branch Name | row 1, full width | Case: Client name / Branch name |
| 2 | Name of Applicant | row 2, full width | Form: Applicant / Co-applicant Name |
| 3 | Name of Employer | row 3, full width | Form: Employer Name |
| 4 | Office Address | row 4, full width | Form: Observed Office Address |
| 5 | PH No | row 5, left | **Not captured** (the case has the applicant's contact number, not the office's) |
| 6 | DOB | row 5, right | **Not captured** |
| 7 | Date of Visit | row 6, left | Form: Date & Time of Visit, date part |
| 8 | Time of Visit | row 6, right | Same, time part |
| 9 | Person Met | row 7, left | Form: Person Met |
| 10 | Designation | row 7, right | Form: Person's Designation |
| 11 | Designation of Applicant | row 8, left | Form: Applicant Designation |
| 12 | No of Years Worked Here | row 8, right | Form: Years in Employment |
| 13 | Terms of Employment | row 10, right | **Not captured** |
| 14 | Type of Employer Co. | row 11, left | **Not captured** |
| 15 | Nature of Business | row 11, right | Form: Nature of Business / Office |
| 16 | Verifier Remarks (red, bold-underlined label + narrative) | single-cell box | Form: Agent Remarks |
| 17 | Remarks (sample "POSITIVE") | row, full width | **Not captured** (see question C) |
| 18 | Recommendation (sample "YES") | row, left | **Not captured** |

**Black and excluded:** title, instruction line, Previous Employment, Year of Establishment, Office Board Present,
Area, No. of Employees, No. of Branches, Premises, Assets Seen, the Comments table (Accessibility, Neighbour's
Feedback), Previously Applied, Reasons-for-Not-Recommended, Verifier Name and Signature.

## 3. Residence Tele Verification Report and Office Tele Verification Report

| # | Red label | Position | CheckSphere source |
|---|---|---|---|
| 1 | Date of Calling | call-log grid, row label (1st–4th attempt columns) | Call attempt log: date |
| 2 | Time of Calling | call-log grid, row label | Call attempt log: time |

Everything else in both telephone formats is black, including the applicant name, address, Person Spoken To,
the "Attempt 1st–4th" header row, the Outcome row and the result.

## 4. ITR Verification Report

Only a fragment inside a black sentence in the Comments cell is red: **"Ack No: & ASSESMENT … 2020-2021"**
(Cambria 12 pt). CheckSphere has no ITR type; ITR documents are handled by Income Verification.

## 5. Formats with NO red content

| VEE format | Red content |
|---|---|
| **KYC Verification Report** | **None.** Everything is black, including Name, PAN / Voter / Aadhaar No. and Remarks |
| **G.S.T. Verification Report** | **None.** Everything is black, including Date / Time of Visit, Name, Business Name / Address, Registration No., Designation, Assessment Year, Status and Remarks |
| Other Bank A/c Verification Report | None |
| Salary Slip Verification Report | None |
| Form 16 Verification Report | None |
| Residence / Office Verification PHOTO pages | None (titles and verifier lines are black) |

Every report **title** in the document is black, for example "Applicant Residence Verification Report".

## 6. CheckSphere request types vs VEE formats

| CheckSphere Request Type | Report type | VEE format |
|---|---|---|
| Residence Verification | residence_applicant | Applicant Residence |
| Office Verification | office_coapplicant | Office |
| Business Verification | business_applicant | Office (closest) |
| Telephone Verification | tel_residence | Residence Tele |
| Income Verification | income | ITR / Salary Slip / Form 16 (no red, apart from the ITR fragment) |
| KYC Verification | kyc | KYC (**no red**) |
| Seller Verification | seller | Residence (closest) |
| Other | custom | none |
| *(none)* | **no GST type exists in CheckSphere** | G.S.T. |
