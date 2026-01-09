# API Documentation Standard for Nominate.AI

This document defines the standard for FastAPI/OpenAPI documentation across all Nominate.AI services. The gold standard reference is **models.nominate.ai** ([/docs](https://models.nominate.ai/docs) | [/redoc](https://models.nominate.ai/redoc)).

---

## Document Structure Overview

```
OpenAPI Specification
├── info                    # API metadata (title, description, contact)
├── servers                 # Environment URLs
├── tags                    # Endpoint groupings with descriptions
├── paths                   # Endpoint definitions
│   └── /api/v1/endpoint
│       ├── summary         # One-line description
│       ├── description     # Detailed markdown documentation
│       ├── tags            # Grouping reference
│       ├── parameters      # Query/path params
│       ├── requestBody     # Input schema
│       └── responses       # Output schemas + examples
└── components
    └── schemas             # Reusable data models
```

---

## 1. API Info Section

Every API MUST include a complete `info` section in FastAPI:

```python
from fastapi import FastAPI

app = FastAPI(
    title="Service Name API",
    description="""
## Overview

Brief description of what this API does and who it's for.

## Key Capabilities

### Feature 1
Description of first major capability.

### Feature 2
Description of second major capability.

## How to Use This API

Step-by-step guidance for consumers.

### Typical Workflow

```
User: "Example query"
API: 1. First step
     2. Second step
     3. Return results
```

## Data Sources

- **Source 1**: Description
- **Source 2**: Description

## Rate Limits

- Endpoint X: Limit per request
- Recommended batch size: X-Y items
""",
    version="1.0.0",
    contact={
        "name": "Team Name",
        "url": "https://github.com/Nominate-AI/repo-name",
        "email": "team@nominate.ai"
    },
    license_info={
        "name": "Proprietary",
        "url": "https://nominate.ai/terms"
    },
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)
```

### Required Info Fields

| Field | Required | Description |
|-------|----------|-------------|
| `title` | Yes | Clear, descriptive API name |
| `description` | Yes | Markdown overview with sections |
| `version` | Yes | Semantic version (1.0.0) |
| `contact.name` | Yes | Team or owner name |
| `contact.url` | Yes | GitHub repo URL |
| `contact.email` | Yes | Team email |
| `license_info` | Yes | License type and URL |

### Description Section Headers

Use these markdown headers in the API description:

1. **Overview** - What the API does (2-3 sentences)
2. **Key Capabilities** - Major features with subsections
3. **How to Use This API** - Integration guidance
4. **Typical Workflow** - Code block showing usage flow
5. **Data Sources** - Backing data with record counts
6. **Rate Limits** - Throughput constraints

---

## 2. Tags (Endpoint Groupings)

Tags organize endpoints into logical categories. Each tag MUST have a description.

```python
from fastapi import FastAPI

app = FastAPI(...)

# Define tags with descriptions
tags_metadata = [
    {
        "name": "segment",
        "description": """
**Segment Analysis Operations**

Analyze voter segments defined by State Voter IDs (SVIDs). These endpoints
compare segment characteristics against the pre-computed baseline.

Use these endpoints when a user asks questions like:
- "How do these voters differ from the general population?"
- "What's unique about this donor segment?"
"""
    },
    {
        "name": "health",
        "description": """
**System Health & Status**

Monitor API health and configuration. Use before making analysis
requests to ensure the system is ready.
"""
    }
]

app = FastAPI(
    ...,
    openapi_tags=tags_metadata
)
```

### Tag Naming Convention

| Tag Name | Use Case |
|----------|----------|
| `health` | Health checks, status endpoints |
| `segment` | Segment analysis operations |
| `baseline` | Reference data access |
| `behavioral` | Behavioral/engagement data |
| `campaign` | Campaign-specific operations |
| `admin` | Administrative operations |

### Tag Description Format

```markdown
**Bold Title**

One paragraph explaining the category purpose.

Use these endpoints when a user asks questions like:
- "Example question 1?"
- "Example question 2?"
- "Example question 3?"
```

---

## 3. Endpoint Documentation

Every endpoint MUST include `summary`, `description`, `tags`, and documented `responses`.

### 3.1 Summary (One-Liner)

Short, action-oriented description (< 60 chars):

```python
@app.post("/api/v1/segment/analyze", tags=["segment"])
async def analyze_segment(...):
    """Analyze voter segment against baseline"""  # This becomes the summary
```

Good summaries:
- "Analyze voter segment against baseline"
- "Get baseline model summary"
- "Check API health status"
- "Enrich segment with behavioral data"

Bad summaries:
- "This endpoint analyzes segments" (verbose)
- "POST segment analysis" (redundant)
- "Segment" (too short)

### 3.2 Description (Detailed)

Use markdown with structured sections:

```python
@app.post("/api/v1/segment/analyze", tags=["segment"])
async def analyze_segment(request: SegmentAnalysisRequest):
    """
    ## Analyze a Voter Segment

    Compare a segment of voters (defined by State Voter IDs) against the full
    voter baseline to identify statistically significant differences.

    ### What This Endpoint Does

    1. **Resolves SVIDs** - Converts State Voter IDs to internal records
    2. **Computes statistics** - Calculates mean, median, distributions
    3. **Compares to baseline** - Identifies deviations from baseline
    4. **Flags significance** - Marks columns with significant differences

    ### Use Cases

    - **Donor Analysis**: "How do Trump donors differ from the population?"
    - **Geographic Targeting**: "What's unique about Miami-Dade voters?"
    - **Behavioral Insights**: "Do email clickers have different demographics?"

    ### Response Interpretation

    The consumer should:
    1. **Start with the summary** - Report segment size and deviations
    2. **Highlight top deviations** - Focus on `summary.top_deviations`
    3. **Explain categorical shifts** - Compare segment vs baseline values
    4. **Note numeric differences** - Use `mean_deviation` percentages

    ### Example Narrative

    ```
    "This segment of 823 voters represents 1% of the baseline.
    They show 8 significant deviations:

    - County: 40% in Miami-Dade (vs 15% baseline) - 2.7x over
    - Age: Average 58.3 (vs 45.2 baseline) - 29% older
    - Party: 72% Republican (vs 45% baseline)"
    ```
    """
```

### Description Section Template

```markdown
## [Action] [Object]

One paragraph explaining what this endpoint does.

### What This Endpoint Does

1. **Step 1** - Description
2. **Step 2** - Description
3. **Step 3** - Description

### Use Cases

- **Use Case 1**: "Example question"
- **Use Case 2**: "Example question"
- **Use Case 3**: "Example question"

### Response Interpretation

How to interpret the response data.

### Example Narrative

```
"Plain English interpretation of typical response..."
```
```

---

## 4. Request/Response Schemas

### 4.1 Schema Definitions

Every Pydantic model MUST include docstrings and field descriptions:

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class SegmentAnalysisRequest(BaseModel):
    """
    Request for segment analysis.

    Provide a list of State Voter IDs to analyze against the baseline.
    """

    svids: List[str] = Field(
        ...,
        min_length=1,
        max_length=100000,
        description="List of State Voter IDs to analyze. Maximum 100,000 per request.",
        json_schema_extra={"examples": [["FL-123456789", "FL-987654321"]]}
    )

    include_patterns: bool = Field(
        default=True,
        description="Include data quality patterns (missing data, imbalance) in results."
    )

    significance_threshold: float = Field(
        default=0.05,
        ge=0.001,
        le=0.5,
        description="P-value threshold for flagging significant deviations. Lower = stricter."
    )

    class Config:
        json_schema_extra = {
            "example": {
                "svids": ["FL-123456789", "FL-987654321", "FL-456789123"],
                "include_patterns": True,
                "significance_threshold": 0.05
            }
        }
```

### 4.2 Response Schema

```python
class SegmentAnalysisResponse(BaseModel):
    """
    Response from segment analysis.

    Contains summary statistics and detailed column-by-column deviations.
    """

    request_id: str = Field(
        description="Unique identifier for this analysis request."
    )

    analyzed_at: datetime = Field(
        description="Timestamp when analysis was performed."
    )

    segment_svids_provided: int = Field(
        description="Number of SVIDs in the original request."
    )

    segment_svids_matched: int = Field(
        description="Number of SVIDs successfully matched to voter records."
    )

    summary: AnalysisSummary = Field(
        description="High-level summary of analysis results."
    )

    columns: List[ColumnDeviation] = Field(
        description="Detailed deviation analysis for each column."
    )

    class Config:
        json_schema_extra = {
            "example": {
                "request_id": "550e8400-e29b-41d4-a716-446655440000",
                "analyzed_at": "2025-12-26T10:30:00Z",
                "segment_svids_provided": 1000,
                "segment_svids_matched": 823,
                "summary": {
                    "segment_size": 823,
                    "baseline_size": 81000,
                    "significant_deviations": 8,
                    "top_deviations": ["county", "age", "party_affiliation"]
                },
                "columns": []
            }
        }
```

### Field Description Requirements

| Element | Required | Description |
|---------|----------|-------------|
| `description` | Yes | Clear explanation of what this field contains |
| `examples` | Yes | Realistic example values |
| Constraints | When applicable | `min_length`, `max_length`, `ge`, `le`, `regex` |
| Default | When applicable | Sensible default with explanation |

---

## 5. Response Status Codes

Document all possible response codes with examples:

```python
from fastapi import HTTPException
from fastapi.responses import JSONResponse

@app.post(
    "/api/v1/segment/analyze",
    responses={
        200: {
            "description": "Successful analysis",
            "content": {
                "application/json": {
                    "example": {
                        "request_id": "550e8400-e29b-41d4-a716-446655440000",
                        "segment_svids_matched": 823,
                        "summary": {"significant_deviations": 8}
                    }
                }
            }
        },
        404: {
            "description": "No matching voters found for provided SVIDs",
            "content": {
                "application/json": {
                    "example": {"detail": "No matching persons found for provided SVIDs"}
                }
            }
        },
        422: {
            "description": "Validation error - invalid input format",
            "content": {
                "application/json": {
                    "example": {"detail": [{"loc": ["body", "svids"], "msg": "field required"}]}
                }
            }
        },
        503: {
            "description": "Service unavailable - model or database not loaded",
            "content": {
                "application/json": {
                    "example": {"detail": "Model not loaded"}
                }
            }
        }
    }
)
async def analyze_segment(request: SegmentAnalysisRequest):
    ...
```

### Standard Response Codes

| Code | Use Case | Required |
|------|----------|----------|
| 200 | Success | Always |
| 201 | Resource created | POST creating resources |
| 400 | Bad request (client error) | When applicable |
| 401 | Unauthorized | Protected endpoints |
| 403 | Forbidden | Role-based access |
| 404 | Not found | Resource lookups |
| 422 | Validation error | FastAPI default |
| 500 | Internal server error | Optional (implicit) |
| 503 | Service unavailable | Dependency failures |

---

## 6. Health Check Endpoint

Every API MUST expose a health check:

```python
class HealthResponse(BaseModel):
    """Health check response with component status."""

    status: str = Field(
        description="Overall health status: 'healthy' or 'degraded'"
    )
    model_loaded: bool = Field(
        description="Whether the ML model is loaded and ready"
    )
    database_connected: bool = Field(
        description="Whether the database connection is active"
    )
    version: str = Field(
        description="API version number"
    )

@app.get(
    "/api/v1/health",
    tags=["health"],
    response_model=HealthResponse,
    responses={
        200: {
            "description": "Current health status of all API components",
            "content": {
                "application/json": {
                    "example": {
                        "status": "healthy",
                        "model_loaded": True,
                        "database_connected": True,
                        "version": "1.0.0"
                    }
                }
            }
        }
    }
)
async def health_check():
    """
    ## Health Check

    Returns the current health status of the API, including:

    - **Model status** - Is the baseline model loaded?
    - **Database status** - Is the database connection active?
    - **Version** - Current API version

    ### Health States

    - **healthy** - All systems operational
    - **degraded** - Some components unavailable (analysis may fail)
    """
```

---

## 7. Documentation Quality Checklist

### API Level
- [ ] Title is descriptive and matches service name
- [ ] Description includes Overview, Capabilities, Workflow sections
- [ ] Contact info with name, URL, email
- [ ] Version follows semantic versioning
- [ ] All tags have descriptions with use cases

### Endpoint Level
- [ ] Summary is < 60 characters, action-oriented
- [ ] Description has What/Use Cases/Interpretation sections
- [ ] All parameters documented with descriptions
- [ ] Request body has example
- [ ] All response codes documented with examples
- [ ] Tags assigned for grouping

### Schema Level
- [ ] Model has docstring explaining purpose
- [ ] Every field has `description`
- [ ] Fields have realistic `examples`
- [ ] Constraints documented (`min_length`, etc.)
- [ ] Response model has complete example

---

## 8. Writing Style Guide

### Do's

- Use **active voice**: "Analyzes voter segments" not "Voter segments are analyzed"
- Start descriptions with **action verbs**: Analyze, Get, Create, Update, Delete
- Include **realistic examples**: Use plausible data, not "foo", "bar"
- Document **edge cases**: What happens with empty input?
- Explain **why**, not just what: "Use this to identify targeting opportunities"

### Don'ts

- Don't use jargon without explanation
- Don't assume prior knowledge of internal systems
- Don't leave fields without descriptions
- Don't use placeholder examples ("string", 0, null)
- Don't skip error response documentation

### Markdown in Descriptions

```markdown
## Heading (main sections)
### Subheading (subsections)
**Bold** for emphasis
`code` for field names, values
- Bullet lists for options
1. Numbered lists for steps
```code blocks``` for examples
| Tables | for | structured data |
```

---

## 9. Example: Complete Endpoint

```python
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class DonorPropensityRequest(BaseModel):
    """
    Request for donor propensity scoring.

    Score voters for likelihood of making a donation based on behavioral signals.
    """

    svids: List[str] = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="State Voter IDs to score for donation propensity.",
        json_schema_extra={"examples": [["FL-123456789", "FL-987654321"]]}
    )

    include_factors: bool = Field(
        default=True,
        description="Include breakdown of scoring factors in response."
    )

    class Config:
        json_schema_extra = {
            "example": {
                "svids": ["FL-123456789", "FL-987654321"],
                "include_factors": True
            }
        }


class DonorPropensityResponse(BaseModel):
    """Donor propensity scores with tier classification."""

    request_id: str = Field(description="Unique request identifier.")
    scored_at: datetime = Field(description="When scoring was performed.")
    svids_provided: int = Field(description="Input SVID count.")
    svids_scored: int = Field(description="Successfully scored count.")

    high_propensity_count: int = Field(
        description="Voters with score > 0.7 (strong donation candidates)."
    )
    medium_propensity_count: int = Field(
        description="Voters with score 0.4-0.7 (cultivation candidates)."
    )
    low_propensity_count: int = Field(
        description="Voters with score < 0.4 (focus on engagement first)."
    )

    class Config:
        json_schema_extra = {
            "example": {
                "request_id": "abc-123",
                "scored_at": "2025-12-26T10:30:00Z",
                "svids_provided": 1000,
                "svids_scored": 950,
                "high_propensity_count": 52,
                "medium_propensity_count": 180,
                "low_propensity_count": 718
            }
        }


@app.post(
    "/api/v1/behavioral/propensity",
    tags=["behavioral"],
    response_model=DonorPropensityResponse,
    summary="Score donor propensity",
    responses={
        200: {
            "description": "Donor propensity scores with tier classification",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/DonorPropensityResponse"}
                }
            }
        },
        422: {
            "description": "Validation Error",
            "content": {
                "application/json": {
                    "example": {"detail": [{"loc": ["body", "svids"], "msg": "field required"}]}
                }
            }
        }
    }
)
async def score_donor_propensity(request: DonorPropensityRequest):
    """
    ## Donor Propensity Scoring

    Score voters for likelihood of making a donation based on behavioral signals.
    Uses a rule-based model that can be upgraded to ML in the future.

    ### Propensity Score Components

    | Factor | Weight | Rationale |
    |--------|--------|-----------|
    | Previous donor | +0.60 | Historical donors most likely to donate again |
    | Click engagement | +0.15 | Clickers show investment in content |
    | Campaign diversity | +0.10 | Engaged across campaigns = committed |
    | Base | +0.10 | Baseline probability |

    ### Score Tiers

    - **High (>0.7)** - Strong candidates for donation asks
    - **Medium (0.4-0.7)** - Cultivation candidates
    - **Low (<0.4)** - Focus on engagement first

    ### Use Cases

    - **Fundraising**: "Who should we ask for donations?"
    - **Prioritization**: "Rank this list by donation likelihood"
    - **Segmentation**: "Split into high/medium/low propensity groups"

    ### Example Interpretation

    ```
    "Of 1000 voters, 52 are high-propensity (>0.7), 180 are medium, 768 are low.
    Top candidate: SVID-123 (score 0.85, previous donor, high engagement)"
    ```
    """
    ...
```

---

## References

- [models.nominate.ai/docs](https://models.nominate.ai/docs) - Swagger UI reference
- [models.nominate.ai/redoc](https://models.nominate.ai/redoc) - ReDoc reference
- [models.nominate.ai/openapi.json](https://models.nominate.ai/openapi.json) - OpenAPI spec
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [OpenAPI 3.1 Specification](https://spec.openapis.org/oas/v3.1.0)
