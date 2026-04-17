# GigShield — IRDAI Regulatory Compliance Framework

**Version:** 1.0  
**Date:** April 2026  
**Regulatory Authority:** Insurance Regulatory and Development Authority of India (IRDAI)  
**Product Category:** Micro-Insurance / Parametric Insurance

---

## 1. Product Classification

GigShield operates as a **parametric micro-insurance** product under:

| Regulation | Reference |
|---|---|
| IRDAI (Micro-Insurance) Regulations 2005 | Product falls under micro-insurance for low-income workers |
| IRDAI (Insurance Products) Regulations 2024 | Parametric trigger-based products |
| IRDAI Sandbox Regulations 2019 | Initial launch under regulatory sandbox (RS/2024/GIG/001) |
| Motor Vehicles Act 1988 (amended) | Riders operating gig vehicles |
| Payment and Settlement Systems Act 2007 | UPI AutoPay mandate compliance |

---

## 2. Licensing Requirements

### 2.1 Required Licenses
- **Primary License:** General Insurance License (under IRDAI Act 1999)
- **Alternate Path:** B2B2C model via licensed insurer partnership (preferred for Phase 1)
  - Partner with: New India Assurance / ICICI Lombard / Bajaj Allianz
  - GigShield acts as Insurance Marketing Firm (IMF) or Corporate Agent

### 2.2 Corporate Agent Registration
Per IRDAI (Registration of Insurance Marketing Firms) Regulations 2015:
```
Required documents:
  □ Certificate of Incorporation
  □ Net worth certificate (min ₹10 lakhs for IMF)
  □ Fit and proper criteria for directors/key management
  □ Infrastructure requirements (IT systems, data security)
  □ Professional indemnity insurance
```

---

## 3. Product Filing Requirements

### 3.1 File-and-Use (F&U) Procedure
Per IRDAI (Use and File) Procedure Regulations 2023:
- Product must be filed within **30 days** of launch
- Required documents: product wordings, prospectus, premium tables, policy conditions

### 3.2 Key Product Clauses Required

```
PARAMETRIC TRIGGER DISCLOSURE:
"This policy pays a pre-defined benefit when a specified 
parametric trigger threshold is met, regardless of actual 
loss incurred. Payout is NOT based on claims submitted by 
the policyholder."

ORACLE DATA SOURCE DISCLOSURE:
"Trigger determination uses data from: OpenWeatherMap, 
WAQI, NDMA, HERE Maps. Data availability is not guaranteed. 
In case of data unavailability exceeding 4 hours, the 
trigger evaluation window is extended by 24 hours."

BASIS RISK DISCLOSURE:
"A basis risk exists where the parametric trigger may fire 
without the policyholder experiencing actual income loss, 
or vice versa. GigShield mitigates this through H3-based 
geospatial targeting and multi-source oracle consensus."
```

---

## 4. Policyholder Protection

### 4.1 Free Look Period
- **15 days** from policy issuance (IRDAI mandate)
- Implementation: `cancel_policy()` with full premium refund within free-look window

### 4.2 Grievance Redressal (IRDAI requirement)
```
Grievance flow (IRDAI Grievance Regulations 2017):
  Day 0:  Complaint received → acknowledgement within 3 business days
  Day 14: Resolution or escalation to Grievance Officer
  Day 30: Final resolution
  
  If unresolved: IRDAI Bima Bharosa portal escalation
  Ombudsman: Insurance Ombudsman (whichever jurisdiction rider resides)
```

### 4.3 Policy Document Requirements (IRDAI mandate)
- [ ] Policy schedule (premium, coverage, term, hub zone)
- [ ] Policy wordings (in Hindi + English)
- [ ] Exclusions clearly stated
- [ ] Claim process (parametric — automated)
- [ ] Grievance contact details
- [ ] IRDAI registration number

---

## 5. Data Protection Compliance

### 5.1 Digital Personal Data Protection Act 2023 (DPDPA)
```python
# GigShield DPDPA implementation:
# ✅ Purpose limitation: GPS/telemetry used ONLY for trigger verification
# ✅ Data minimization: Aadhaar/PAN stored as SHA-256 hash only
# ✅ Consent: Explicit consent collected during onboarding
# ✅ Right to erasure: data_retention_service.py handles TTL
# ✅ Data localization: All data stored on Indian Supabase region (ap-south-1)
```

### 5.2 Aadhaar Compliance (UIDAI)
- Aadhaar number **never stored in plaintext** — SHA-256 hash only
- e-KYC via DigiLocker API (planned) or Aadhaar OTP (licensed VUA required)
- Offline KYC XML verification as alternative

### 5.3 UPI/RBI Compliance
- Razorpay X (payout API) — licensed PA under RBI Payment Aggregator framework
- AutoPay mandate: NACH/UPI mandate compliant with NPCI guidelines
- TDS deduction: tracked via `annual_payout_total` — ₹1 lakh threshold triggers Form 15G/H collection

---

## 6. Anti-Money Laundering (AML)

Per PMLA 2002 and IRDAI AML/CFT Guidelines:
```
KYC requirements:
  ✅ Phone verification (OTP)
  □ PAN verification (for payouts > ₹50,000 cumulative)
  □ Aadhaar e-KYC (for enhanced KYC)
  □ Address verification (delivery platform API)

Transaction monitoring:
  ✅ Fraud score system (3-layer: intent, presence, Bayesian)
  ✅ Geospatial fraud clustering (DBSCAN)
  ✅ Velocity checks (GPS > 150 km/h hard-flag)
  ✅ Manual review queue for suspicious claims
```

---

## 7. Solvency Requirements

Per IRDAI (Assets, Liabilities and Solvency Margin) Regulations 2016:
```
Minimum Solvency Ratio: 1.5× (IRDAI minimum: 1.5×)
GigShield target:        2.0× (conservative buffer)

Implementation:
  - liquidity_service.py monitors real-time solvency
  - kill_switch activates at: ratio < 1.5×
  - Admin alert at: ratio < 1.8×
  - Reserve buffer: ₹5 lakhs minimum (configurable via system_config)
```

---

## 8. GST Compliance

| Service | GST Rate | HSN/SAC |
|---|---|---|
| Insurance premium | 18% | SAC 997135 |
| Claims payout | Exempt | — |
| B2B API access fees | 18% | SAC 998319 |

**Implementation:** Premium amounts shown include GST. GST invoices auto-generated monthly.

---

## 9. Regulatory Sandbox Application

### Phase 1: Sandbox (0-6 months)
- Apply under IRDAI Regulatory Sandbox Regulations 2019
- Max participants: 10,000 riders
- Duration: 12 months extendable
- City scope: Mumbai + Bangalore
- Required: Half-yearly progress reports to IRDAI

### Phase 2: Full License (6-18 months)
- File for Insurance Intermediary License
- OR partner with licensed insurer for white-label
- Scale to 5 cities, 100,000 riders

---

## 10. Platform Partner Agreements

For B2B integration with Zepto/Blinkit/Instamart:
```
Required clauses:
  □ Data sharing agreement (rider GPS, platform status)
  □ Revenue sharing terms (typically 15-20% of premium)
  □ Exclusivity terms (optional)
  □ Co-branded insurance disclosure requirements
  □ Customer data protection responsibilities
  □ IRDAI corporate agent sub-delegation (if applicable)
```

---

*Document owner: GigShield Legal & Compliance Team*  
*Next review: October 2026*  
*IRDAI sandbox reference: RS/2024/GIG/001 (pending)*
