# RCM Oman

Revenue cycle for Marley Health in Oman: copay rules, eligibility (direct and manual with check-in
gate), prior authorisation with payer-share cap, pre-submission claim validation, claim dispatch
(Dhamani or manual Excel pack), partial payer adjudication, remittance to Payment Entry, denial
cases (resubmit / write off / re-bill patient), reports, *Revenue Cycle* workspace.

Transports plug in through the `rcm_transport` hook (see `rcm_oman/transport.py`); the canonical
message model is in `rcm_oman/canonical.py`.

Requires: frappe, erpnext, healthcare, his_oman. See INSTALL.md in the bundle.
License: GPL-3.0
