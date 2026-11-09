# Raw Reference

**Raw** endpoints, reached through `with_raw_response`, return `ApiResult[T, E]` and never raise for an API error. For the parsed endpoints, see [API Reference](api-reference.md).

> Source: [PartnerReferralsClient](partner_referrals/client.py)

<details>
<summary><code>def partner_referrals_create(body: CustomerData | CustomerDataDict, *, request_options: RequestOptionsOrDict | None = None) -> ApiResult[CreateReferralDataResponse, PartnerReferralsCreateErrorBody]</code></summary>

<dl>
<dd>

### Description

<dl>
<dd>

Creates a partner referral that is shared by the partner or API caller. The partner referral is used to onboard the seller, and contains the seller's personal, business, financial and operations.

</dd>
</dl>

### Usage

<dl>
<dd>

**Sync**

```python
result = client.with_raw_response.partner_referrals_create(
    CustomerData(
        operations=[Operation(operation=Operation1.API_INTEGRATION)], legal_consents=[LegalConsent(granted=True)]
    ),
)
match result:
    case Success(payload=payload):
        ...  # TODO: Handle 'payload' of type CreateReferralDataResponse
    case Failure(error=error):
        ...  # TODO: Handle 'error' of type PartnerReferralsCreateErrorBody
```

**Async**

```python
result = await async_client.with_raw_response.partner_referrals_create(
    CustomerData(
        operations=[Operation(operation=Operation1.API_INTEGRATION)], legal_consents=[LegalConsent(granted=True)]
    ),
)
match result:
    case Success(payload=payload):
        ...  # TODO: Handle 'payload' of type CreateReferralDataResponse
    case Failure(error=error):
        ...  # TODO: Handle 'error' of type PartnerReferralsCreateErrorBody
```

</dd>
</dl>

### Parameters

<dl>
<dd>

| Name | Type | Description |
| --- | --- | --- |
| <code>body</code> | <code>[CustomerData](partner_referrals/models/customer_data.py) \| [CustomerDataDict](partner_referrals/models/customer_data.py)</code> | The request body. |
| <code>request_options</code> | <code>[RequestOptionsOrDict](partner_referrals/core/request_options.py) \| None</code> | Per-call overrides for this one request, such as a timeout, extra headers, or its retry count and statuses. |

</dd>
</dl>

### Response

<dl>
<dd>

**Returns**: <code>[ApiResult](partner_referrals/core/results.py)&#91;[CreateReferralDataResponse](partner_referrals/models/create_referral_data_response.py), [PartnerReferralsCreateErrorBody](partner_referrals/errors/partner_referrals_create_error.py)&#93;</code>

**On `Success`**: `payload` is <code>[CreateReferralDataResponse](partner_referrals/models/create_referral_data_response.py)</code> -- A successful request returns the HTTP `201 Created` status code and a JSON response body that contains a [HATEOAS link](/docs/api/overview/#hateoas-links) to show the referral data and an `action_url` to which you redirect the customer in a browser to complete the signup process. The `partner_referral_id` token is appended to the URL.

**On `Failure`**: `error` is <code>[PartnerReferralsCreateErrorBody](partner_referrals/errors/partner_referrals_create_error.py)</code>

Mapped in first-match order -- an earlier row wins over a later range that also covers the status:

| Status | `error` is |
| --- | --- |
| 400 | <code>[V2CustomerPartnerReferrals400Error1](partner_referrals/models/v2_customer_partner_referrals400_error1.py)</code> |
| 401 | <code>[V2CustomerPartnerReferrals401Error1](partner_referrals/models/v2_customer_partner_referrals401_error1.py)</code> |
| 403 | <code>[V2CustomerPartnerReferrals403Error1](partner_referrals/models/v2_customer_partner_referrals403_error1.py)</code> |
| 422 | <code>[V2CustomerPartnerReferrals422Error1](partner_referrals/models/v2_customer_partner_referrals422_error1.py)</code> |
| 500 | <code>[InternalServerError](partner_referrals/models/internal_server_error.py)</code> |
| anything unmapped | <code>[RawError](partner_referrals/core/results.py)</code> |

</dd>
</dl>

</dd>
</dl>

</details>

<details>
<summary><code>def partner_referrals_read(partner_referral_id: str, *, request_options: RequestOptionsOrDict | None = None) -> ApiResult[ReferralDataResponse, PartnerReferralsReadErrorBody]</code></summary>

<dl>
<dd>

### Description

<dl>
<dd>

Shows details by ID for referral data that was shared by the partner or API caller.

</dd>
</dl>

### Usage

<dl>
<dd>

**Sync**

```python
result = client.with_raw_response.partner_referrals_read("some example string")
match result:
    case Success(payload=payload):
        ...  # TODO: Handle 'payload' of type ReferralDataResponse
    case Failure(error=error):
        ...  # TODO: Handle 'error' of type PartnerReferralsReadErrorBody
```

**Async**

```python
result = await async_client.with_raw_response.partner_referrals_read("some example string")
match result:
    case Success(payload=payload):
        ...  # TODO: Handle 'payload' of type ReferralDataResponse
    case Failure(error=error):
        ...  # TODO: Handle 'error' of type PartnerReferralsReadErrorBody
```

</dd>
</dl>

### Parameters

<dl>
<dd>

| Name | Type | Description |
| --- | --- | --- |
| <code>partner_referral_id</code> | <code>str</code> | The ID of the partner-referrals data for which to show details. |
| <code>request_options</code> | <code>[RequestOptionsOrDict](partner_referrals/core/request_options.py) \| None</code> | Per-call overrides for this one request, such as a timeout, extra headers, or its retry count and statuses. |

</dd>
</dl>

### Response

<dl>
<dd>

**Returns**: <code>[ApiResult](partner_referrals/core/results.py)&#91;[ReferralDataResponse](partner_referrals/models/referral_data_response.py), [PartnerReferralsReadErrorBody](partner_referrals/errors/partner_referrals_read_error.py)&#93;</code>

**On `Success`**: `payload` is <code>[ReferralDataResponse](partner_referrals/models/referral_data_response.py)</code> -- A successful request returns the HTTP `200 OK` status code and a JSON response body that shows referral data.

**On `Failure`**: `error` is <code>[PartnerReferralsReadErrorBody](partner_referrals/errors/partner_referrals_read_error.py)</code>

Mapped in first-match order -- an earlier row wins over a later range that also covers the status:

| Status | `error` is |
| --- | --- |
| 401 | <code>[V2CustomerPartnerReferrals401Error1](partner_referrals/models/v2_customer_partner_referrals401_error1.py)</code> |
| 403 | <code>[V2CustomerPartnerReferrals403Error1](partner_referrals/models/v2_customer_partner_referrals403_error1.py)</code> |
| 500 | <code>[InternalServerError](partner_referrals/models/internal_server_error.py)</code> |
| anything unmapped | <code>[RawError](partner_referrals/core/results.py)</code> |

</dd>
</dl>

</dd>
</dl>

</details>

