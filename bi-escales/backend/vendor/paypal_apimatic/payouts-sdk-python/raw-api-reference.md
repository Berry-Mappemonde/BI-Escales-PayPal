# Raw Reference

**Raw** endpoints, reached through `with_raw_response`, return `ApiResult[T, E]` and never raise for an API error. For the parsed endpoints, see [API Reference](api-reference.md).

> Source: [PayoutsClient](payouts/client.py)

## Payouts

> Source: [Payouts](payouts/apis/payouts.py)

<details>
<summary><code>def payouts_get(id_: str, *, fields: str | None = None, page: int | None = 1, page_size: int | None = None, total_required: bool | None = False, request_options: RequestOptionsOrDict | None = None) -> ApiResult[PayoutBatch, PayoutsGetErrorBody]</code></summary>

<dl>
<dd>

### Description

<dl>
<dd>

Shows the latest status of a batch payout. Includes the transaction status and other data for individual payout items.

</dd>
</dl>

### Usage

<dl>
<dd>

**Sync**

```python
result = client.payouts.with_raw_response.payouts_get("some example string")
match result:
    case Success(payload=payload):
        ...  # TODO: Handle 'payload' of type PayoutBatch
    case Failure(error=error):
        ...  # TODO: Handle 'error' of type PayoutsGetErrorBody
```

**Async**

```python
result = await async_client.payouts.with_raw_response.payouts_get("some example string")
match result:
    case Success(payload=payload):
        ...  # TODO: Handle 'payload' of type PayoutBatch
    case Failure(error=error):
        ...  # TODO: Handle 'error' of type PayoutsGetErrorBody
```

</dd>
</dl>

### Parameters

<dl>
<dd>

| Name | Type | Description |
| --- | --- | --- |
| <code>id_</code> | <code>str</code> | The ID of the payout for which to show details. |
| <code>fields</code> | <code>str \| None</code> | Shows details for only the specified fields.<br>**Default**: <code>None</code> |
| <code>page</code> | <code>int \| None</code> | A non-zero integer representing the page of the results.<br>**Default**: <code>1</code> |
| <code>page_size</code> | <code>int \| None</code> | The maximum number of results to return at one time. Value is a non-negative, non-zero integer. If the user chooses pagination, the maximum page is `1000`.<br>**Default**: <code>None</code> |
| <code>total_required</code> | <code>bool \| None</code> | Indicates whether to show the total items and total pages count in the response.<br>**Default**: <code>False</code> |
| <code>request_options</code> | <code>[RequestOptionsOrDict](payouts/core/request_options.py) \| None</code> | Per-call overrides for this one request, such as a timeout, extra headers, or its retry count and statuses. |

</dd>
</dl>

### Response

<dl>
<dd>

**Returns**: <code>[ApiResult](payouts/core/results.py)&#91;[PayoutBatch](payouts/models/payout_batch.py), [PayoutsGetErrorBody](payouts/errors/payouts_get_error.py)&#93;</code>

**On `Success`**: `payload` is <code>[PayoutBatch](payouts/models/payout_batch.py)</code> -- A successful request returns the HTTP `200 OK` status code and a JSON response body that shows batch payout details.

**On `Failure`**: `error` is <code>[PayoutsGetErrorBody](payouts/errors/payouts_get_error.py)</code>

Mapped in first-match order -- an earlier row wins over a later range that also covers the status:

| Status | `error` is |
| --- | --- |
| 404, 500 | <code>[Error](payouts/models/error.py)</code> |
| anything unmapped | <code>[RawError](payouts/core/results.py)</code> |

</dd>
</dl>

</dd>
</dl>

</details>

<details>
<summary><code>def payouts_post(*, pay_pal_request_id: str | None = None, body: CreatePayoutRequest | CreatePayoutRequestDict | None = None, request_options: RequestOptionsOrDict | None = None) -> ApiResult[CreatePayoutResponse, PayoutsPostErrorBody]</code></summary>

<dl>
<dd>

### Description

<dl>
<dd>

Creates a batch payout. In the JSON request body, pass a `sender_batch_header` and an `items` array. The `sender_batch_header` defines how to handle the payout. The `items` array defines the payout items.<br/>You can make payouts to one or more recipients.<blockquote><strong>Notes:</strong> <ul><li><p>PayPal does not process duplicate payouts. If you specify a <code>sender_batch_id</code> that was used in the last 30 days, the API rejects the request with an error message that shows the duplicate <code>sender_batch_id</code> and includes a HATEOAS link to the original payout with the same <code>sender_batch_id</code>.</p><p>If you receive an HTTP <code>5<i>nn</i></code> status code, you can safely retry the request with the same <code>sender_batch_id</code>.</p></li><li><p>The Payouts API does not support build notation (BN) codes. In a future Payouts release, you can optionally provide BN codes in the <code>PayPal-Partner-Attribution-Id</code> request header.</p><p>For information about the <code>PayPal-Partner-Attribution-Id</code> header, see <a href="/api/rest/requests/#http-request-headers">HTTP request headers</a>. To learn about or request a BN code, contact your partner manager or see <a href="https://www.paypal.com/us/webapps/mpp/partner-program">PayPal Partner Program</a>.</p></li></ul></blockquote>

</dd>
</dl>

### Usage

<dl>
<dd>

**Sync**

```python
result = client.payouts.with_raw_response.payouts_post(
    body=CreatePayoutRequest(
        sender_batch_header=SenderBatchHeader(
            sender_batch_id="Payouts_2018_100007",
            email_subject="You have a payout!",
            email_message="You have received a payout! Thanks for using our service!",
        ),
        items=[
            PayoutItem(
                recipient_type="EMAIL",
                amount=Currency(currency="USD", value="9.87"),
                note="Thanks for your patronage!",
                receiver="receiver@example.com",
                sender_item_id="201403140001",
                alternate_notification_method=AlternateNotificationMethod(phone=Phone()),
                notification_language="fr-FR",
            ),
            PayoutItem(
                recipient_type="PHONE",
                amount=Currency(currency="USD", value="112.34"),
                note="Thanks for your support!",
                receiver="91-734-234-1234",
                sender_item_id="201403140002",
            ),
            PayoutItem(
                recipient_type="PAYPAL_ID",
                amount=Currency(currency="USD", value="5.32"),
                note="Thanks for your patronage!",
                receiver="G83JXTJ5EHCQ2",
                sender_item_id="201403140003",
            ),
        ],
    ),
)
match result:
    case Success(payload=payload):
        ...  # TODO: Handle 'payload' of type CreatePayoutResponse
    case Failure(error=error):
        ...  # TODO: Handle 'error' of type PayoutsPostErrorBody
```

**Async**

```python
result = await async_client.payouts.with_raw_response.payouts_post(
    body=CreatePayoutRequest(
        sender_batch_header=SenderBatchHeader(
            sender_batch_id="Payouts_2018_100007",
            email_subject="You have a payout!",
            email_message="You have received a payout! Thanks for using our service!",
        ),
        items=[
            PayoutItem(
                recipient_type="EMAIL",
                amount=Currency(currency="USD", value="9.87"),
                note="Thanks for your patronage!",
                receiver="receiver@example.com",
                sender_item_id="201403140001",
                alternate_notification_method=AlternateNotificationMethod(phone=Phone()),
                notification_language="fr-FR",
            ),
            PayoutItem(
                recipient_type="PHONE",
                amount=Currency(currency="USD", value="112.34"),
                note="Thanks for your support!",
                receiver="91-734-234-1234",
                sender_item_id="201403140002",
            ),
            PayoutItem(
                recipient_type="PAYPAL_ID",
                amount=Currency(currency="USD", value="5.32"),
                note="Thanks for your patronage!",
                receiver="G83JXTJ5EHCQ2",
                sender_item_id="201403140003",
            ),
        ],
    ),
)
match result:
    case Success(payload=payload):
        ...  # TODO: Handle 'payload' of type CreatePayoutResponse
    case Failure(error=error):
        ...  # TODO: Handle 'error' of type PayoutsPostErrorBody
```

</dd>
</dl>

### Parameters

<dl>
<dd>

| Name | Type | Description |
| --- | --- | --- |
| <code>pay_pal_request_id</code> | <code>str \| None</code> | The server stores keys for 30 days.<br>**Default**: <code>None</code> |
| <code>body</code> | <code>[CreatePayoutRequest](payouts/models/create_payout_request.py) \| [CreatePayoutRequestDict](payouts/models/create_payout_request.py) \| None</code> | The request body.<br>**Default**: <code>None</code> |
| <code>request_options</code> | <code>[RequestOptionsOrDict](payouts/core/request_options.py) \| None</code> | Per-call overrides for this one request, such as a timeout, extra headers, or its retry count and statuses. |

</dd>
</dl>

### Response

<dl>
<dd>

**Returns**: <code>[ApiResult](payouts/core/results.py)&#91;[CreatePayoutResponse](payouts/models/create_payout_response.py), [PayoutsPostErrorBody](payouts/errors/payouts_post_error.py)&#93;</code>

**On `Success`**: `payload` is <code>[CreatePayoutResponse](payouts/models/create_payout_response.py)</code> -- A successful request returns the HTTP <code>201 Created</code> status code and a JSON response body that shows the ID for the payout and payout details. To show payout status, use the <code>payout_batch_id</code> value that appears in the response. If the initial scan that checks for syntax errors, missing or duplicated keywords, and more succeeds, the <code>batch_status</code> is <code>PENDING</code>. The initial scan checks for syntax errors and missing or duplicated keywords. The API does not immediately validate some payout item values, such as the receiver phone numbers.

**On `Failure`**: `error` is <code>[PayoutsPostErrorBody](payouts/errors/payouts_post_error.py)</code>

Mapped in first-match order -- an earlier row wins over a later range that also covers the status:

| Status | `error` is |
| --- | --- |
| 400, 403, 500 | <code>[Error](payouts/models/error.py)</code> |
| anything unmapped | <code>[RawError](payouts/core/results.py)</code> |

</dd>
</dl>

</dd>
</dl>

</details>

## PayoutsItem

> Source: [PayoutsItem](payouts/apis/payouts_item.py)

<details>
<summary><code>def payouts_item_cancel(payout_item_id: str, *, request_options: RequestOptionsOrDict | None = None) -> ApiResult[PayoutItem2, PayoutsItemCancelErrorBody]</code></summary>

<dl>
<dd>

### Description

<dl>
<dd>

Cancels an unclaimed payout item, by ID. If no one claims the unclaimed item within 30 days, the API automatically returns the funds to the sender. Use this call to cancel the unclaimed item before the automatic 30-day refund. You can cancel payout items with a <code>transaction_status</code> of <code>UNCLAIMED</code>.

</dd>
</dl>

### Usage

<dl>
<dd>

**Sync**

```python
result = client.payouts_item.with_raw_response.payouts_item_cancel("some example string")
match result:
    case Success(payload=payload):
        ...  # TODO: Handle 'payload' of type PayoutItem2
    case Failure(error=error):
        ...  # TODO: Handle 'error' of type PayoutsItemCancelErrorBody
```

**Async**

```python
result = await async_client.payouts_item.with_raw_response.payouts_item_cancel("some example string")
match result:
    case Success(payload=payload):
        ...  # TODO: Handle 'payload' of type PayoutItem2
    case Failure(error=error):
        ...  # TODO: Handle 'error' of type PayoutsItemCancelErrorBody
```

</dd>
</dl>

### Parameters

<dl>
<dd>

| Name | Type | Description |
| --- | --- | --- |
| <code>payout_item_id</code> | <code>str</code> | The ID of the payout item to cancel. |
| <code>request_options</code> | <code>[RequestOptionsOrDict](payouts/core/request_options.py) \| None</code> | Per-call overrides for this one request, such as a timeout, extra headers, or its retry count and statuses. |

</dd>
</dl>

### Response

<dl>
<dd>

**Returns**: <code>[ApiResult](payouts/core/results.py)&#91;[PayoutItem2](payouts/models/payout_item2.py), [PayoutsItemCancelErrorBody](payouts/errors/payouts_item_cancel_error.py)&#93;</code>

**On `Success`**: `payload` is <code>[PayoutItem2](payouts/models/payout_item2.py)</code> -- A successful request returns the HTTP `200 OK` status code with a JSON response body that shows payout item details.

**On `Failure`**: `error` is <code>[PayoutsItemCancelErrorBody](payouts/errors/payouts_item_cancel_error.py)</code>

Mapped in first-match order -- an earlier row wins over a later range that also covers the status:

| Status | `error` is |
| --- | --- |
| 400, 404, 500 | <code>[Error](payouts/models/error.py)</code> |
| anything unmapped | <code>[RawError](payouts/core/results.py)</code> |

</dd>
</dl>

</dd>
</dl>

</details>

<details>
<summary><code>def payouts_item_get(payout_item_id: str, *, request_options: RequestOptionsOrDict | None = None) -> ApiResult[PayoutItem2, PayoutsItemGetErrorBody]</code></summary>

<dl>
<dd>

### Description

<dl>
<dd>

Shows details for a payout item, by ID. A <code>payout_item_id</code> helps you identify denied payments. If a payment is denied, you can use the <code>payout_item_id</code> to identify the payment even if it lacks a <code>transaction_id</code>.

</dd>
</dl>

### Usage

<dl>
<dd>

**Sync**

```python
result = client.payouts_item.with_raw_response.payouts_item_get("some example string")
match result:
    case Success(payload=payload):
        ...  # TODO: Handle 'payload' of type PayoutItem2
    case Failure(error=error):
        ...  # TODO: Handle 'error' of type PayoutsItemGetErrorBody
```

**Async**

```python
result = await async_client.payouts_item.with_raw_response.payouts_item_get("some example string")
match result:
    case Success(payload=payload):
        ...  # TODO: Handle 'payload' of type PayoutItem2
    case Failure(error=error):
        ...  # TODO: Handle 'error' of type PayoutsItemGetErrorBody
```

</dd>
</dl>

### Parameters

<dl>
<dd>

| Name | Type | Description |
| --- | --- | --- |
| <code>payout_item_id</code> | <code>str</code> | The ID of the payout item to cancel. |
| <code>request_options</code> | <code>[RequestOptionsOrDict](payouts/core/request_options.py) \| None</code> | Per-call overrides for this one request, such as a timeout, extra headers, or its retry count and statuses. |

</dd>
</dl>

### Response

<dl>
<dd>

**Returns**: <code>[ApiResult](payouts/core/results.py)&#91;[PayoutItem2](payouts/models/payout_item2.py), [PayoutsItemGetErrorBody](payouts/errors/payouts_item_get_error.py)&#93;</code>

**On `Success`**: `payload` is <code>[PayoutItem2](payouts/models/payout_item2.py)</code> -- A successful request returns the HTTP <code>200 OK</code> status code and a JSON response body with a <code>payout_item_details</code> object, which contains data about a payout item including the transaction status.

**On `Failure`**: `error` is <code>[PayoutsItemGetErrorBody](payouts/errors/payouts_item_get_error.py)</code>

Mapped in first-match order -- an earlier row wins over a later range that also covers the status:

| Status | `error` is |
| --- | --- |
| 404, 500 | <code>[Error](payouts/models/error.py)</code> |
| anything unmapped | <code>[RawError](payouts/core/results.py)</code> |

</dd>
</dl>

</dd>
</dl>

</details>

