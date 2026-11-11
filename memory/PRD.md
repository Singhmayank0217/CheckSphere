# CheckSphere — Field Verification Management System (PRD)

## Original problem statement
A private, secure field-verification management system for the company (CheckSphere branding only — no bank branding/logins). It has two connected products on one secure backend: (1) an Android field agent app (private APK) and (2) a responsive web dashboard for Super Admin and Supervisors. It manages residence, office/business, telephone, income, KYC, seller, bank-account and custom verification reports. It collects factual field evidence (GPS, in-app camera photos, call logs), keeps a full audit trail, protects applicant data (masking, private storage, RBAC), and produces Word/PDF/Excel exports and MIS. The full spec is in the first user message (roles, forms, safe language, submission controls, workflow, flags, exports, security).

## User choices
- Company: **CheckSphere**, light professional palette (deep green #1F4E3D on warm stone)
- Full MVP in one build, including a basic telephone call-attempt log
- Demo data seeded

## Architecture
- **Backend:** FastAPI (`/app/backend`), MongoDB (motor, tz_aware). Modules: core, security (JWT + DB sessions, bcrypt, role guards, case scoping), report_config (11 report types, config-driven forms), storage_service (Emergent Object Storage, private), exporters (python-docx, reportlab + segno QR, openpyxl), and routers for auth/admin/cases/reports/evidence/dashboard/exports/audit. Seeded on an empty DB.
- **Frontend:** Expo Router SDK 58. `(agent)` tabs (Home/Cases/Profile; NativeTabs on iOS 26+), `case/[id]`, `report/[caseId]`, `camera` (expo-camera, in-app only). `(admin)` sidebar console: dashboard, cases, cases/[id] review, cases-new (create + Excel import), users, master, map, audit, mis.
- **Security:** must_change_password gate enforced server-side, session revocation on reset/deactivate, device/IP logged, private files are served only via an authenticated endpoint (header or `?token=`), masking with an audited reveal, blocked-word scan, immutable audit log, AES-encrypted offline drafts (key in SecureStore).

## Implemented (2026-06)
- Auth with forced password change, 15-min inactivity logout, sessions list and revoke
- User management (create, reset, activate/deactivate, sessions); clients, branches, regions; settings (flag thresholds, telephone min attempts, retention, blocked words, company name)
- Case create, Excel import plus template, assign/reassign, filters, pagination, soft delete, timeline
- Agent home KPIs, sync badge, cases with filter chips, case detail with OSM map, config-driven report form, GPS and visit start, camera photo slots with retake, call-attempt log, declaration, draft save (local encrypted plus server), submit with blocking validation
- Review: under-review on open, approve, return (comment mandatory), inconclusive, exception, escalate; versions; flags (GPS missing/low accuracy/distance, duplicate photos, impossible travel, same place/time, late SLA, no visit start)
- Dashboard stats (status counts, TAT, agent/supervisor/client/branch/state/city), map view, audit log
- Exports: case DOCX/PDF (branding, disclaimer, QR link, evidence refs, version), cases.xlsx, MIS daily/weekly/monthly xlsx
- Tested: iteration_1 and iteration_2 (backend 17/17, frontend flows pass)

## Backlog
- P1: Supervisor scope editor UI (the backend already supports client/state/city/branch scope); report template builder UI for custom forms; mock-location detection on native; retention purge job and daily backup job; incident/breach log screen
- P1: Branded logo upload for exports; notifications list for agents
- P2: Advanced offline photo queue (photos currently need connectivity to upload); EXIF/altered-image analysis; supervisor productivity filters; mobile admin layout
