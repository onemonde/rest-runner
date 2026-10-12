# 📋 Execution Report: {{ executions.suite_title }}

> **CIP (Test Identification Code):** `{{ executions.cip }}`  
> **Date:** {{ executions.created_at }}  
> **Total Tests Executed:** {{ total_tests }}

---

{% for test in tests %}
## [Test #{{ test.test_number }}] {{ test.description }}

```bash
{{ test.curl_command }}
```
- **Duration:** {{ test.duration_ms }} ms  
{% if test.error %}
- **Error:** `{{ test.error }}`
{% else %}
- **HTTP Response Status:** `{{ test.res_status }}`

### Response Body
```json
{{ test.res_body_pretty }}
```
{% endif %}

---
{% endfor %}
