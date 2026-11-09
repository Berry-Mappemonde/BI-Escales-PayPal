<!-- Generated file — do not edit; regenerated with the SDK. -->

# Client — operations

Accessor: `client` · Source: `partner_referrals/client.py` · 2 operations

Each `###` block is one operation and assumes `sdk-map.md` is loaded: blocks omit what its invariants table covers and are otherwise self-contained, so chunk at block level. Signatures are the sync parsed spelling; the async and raw spellings take the same parameters (see sdk-map.md). **Type sources** names the module declaring each type an operation mentions, so resolving a body, return or error payload is a lookup rather than a search; the runtime types `RawError` and `ApiResult` are excluded.

### client.partner_referrals_create

- **Route**: `POST /v2/customer/partner-referrals`
- **Auth**: `oauth2`
- **Signature**: `def partner_referrals_create(body: CustomerData | CustomerDataDict, *, request_options: RequestOptionsOrDict | None = None)`
  - required, positional: `body`
- **Params**: `body` — JSON body
- **Returns (parsed)**: `CreateReferralDataResponse`
- **Returns (raw)**: `ApiResult[CreateReferralDataResponse, PartnerReferralsCreateErrorBody]`
- **Error**: `PartnerReferralsCreateErrorBody` — **Case A (typed)**
- **Error arms**: `V2CustomerPartnerReferrals400Error1` [400] · `V2CustomerPartnerReferrals401Error1` [401] · `V2CustomerPartnerReferrals403Error1` [403] · `V2CustomerPartnerReferrals422Error1` [422] · `InternalServerError` [500] · `RawError` [anything unmapped]

| Type | Source |
| --- | --- |
| `CustomerData` | `partner_referrals/models/customer_data.py` |
| `CustomerDataDict` | `partner_referrals/models/customer_data.py` |
| `CreateReferralDataResponse` | `partner_referrals/models/create_referral_data_response.py` |
| `PartnerReferralsCreateErrorBody` | `partner_referrals/errors/partner_referrals_create_error.py` |
| `V2CustomerPartnerReferrals400Error1` | `partner_referrals/models/v2_customer_partner_referrals400_error1.py` |
| `V2CustomerPartnerReferrals401Error1` | `partner_referrals/models/v2_customer_partner_referrals401_error1.py` |
| `V2CustomerPartnerReferrals403Error1` | `partner_referrals/models/v2_customer_partner_referrals403_error1.py` |
| `V2CustomerPartnerReferrals422Error1` | `partner_referrals/models/v2_customer_partner_referrals422_error1.py` |
| `InternalServerError` | `partner_referrals/models/internal_server_error.py` |

### client.partner_referrals_read

- **Route**: `GET /v2/customer/partner-referrals/{partner_referral_id}`
- **Auth**: `oauth2` OR `oauth2`
- **Signature**: `def partner_referrals_read(partner_referral_id: str, *, request_options: RequestOptionsOrDict | None = None)`
  - required, positional: `partner_referral_id`
- **Params**: `partner_referral_id` — path
- **Returns (parsed)**: `ReferralDataResponse`
- **Returns (raw)**: `ApiResult[ReferralDataResponse, PartnerReferralsReadErrorBody]`
- **Error**: `PartnerReferralsReadErrorBody` — **Case A (typed)**
- **Error arms**: `V2CustomerPartnerReferrals401Error1` [401] · `V2CustomerPartnerReferrals403Error1` [403] · `InternalServerError` [500] · `RawError` [anything unmapped]

| Type | Source |
| --- | --- |
| `ReferralDataResponse` | `partner_referrals/models/referral_data_response.py` |
| `PartnerReferralsReadErrorBody` | `partner_referrals/errors/partner_referrals_read_error.py` |
| `V2CustomerPartnerReferrals401Error1` | `partner_referrals/models/v2_customer_partner_referrals401_error1.py` |
| `V2CustomerPartnerReferrals403Error1` | `partner_referrals/models/v2_customer_partner_referrals403_error1.py` |
| `InternalServerError` | `partner_referrals/models/internal_server_error.py` |

