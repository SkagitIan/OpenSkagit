# openskagit/ai/methodology_schemas.py

from pydantic import BaseModel
from typing import List

class StatCard(BaseModel):
    key: str
    label: str
    value: str
    helper_text: str

class GlanceSection(BaseModel):
    title: str
    subtitle: str
    stat_cards: List[StatCard]

class HowModelWorksStep(BaseModel):
    step_number: int
    title: str
    summary: str
    bullet_points: List[str]
    why_it_matters: str

class HowModelWorksSection(BaseModel):
    title: str
    intro: str
    steps: List[HowModelWorksStep]

class RunSegment(BaseModel):
    market_group: str
    value_tier: str
    value_range: str
    n: int
    r2: float
    adj_r2: float
    cod: float
    prd: float
    prb: float
    median_ratio: float
    flags: List[str]
    predictors_used: List[str]

class RunsSection(BaseModel):
    title: str
    intro: str
    run_id: str
    run_timestamp: str
    segments: List[RunSegment]

class FeatureImportanceCard(BaseModel):
    name: str
    short_title: str
    plain_explanation: str
    run_behavior: str
    example: str
    seen_in: List[str]
    importance_note: str

class FeatureImportanceSection(BaseModel):
    title: str
    intro: str
    cards: List[FeatureImportanceCard]

class FAQItem(BaseModel):
    question: str
    answer: str
    why_it_matters: str

class FAQSection(BaseModel):
    title: str
    items: List[FAQItem]

class ModelMethodologyPage(BaseModel):
    page_title: str
    page_tagline: str
    last_model_update: str
    current_model_at_glance: GlanceSection
    how_model_works: HowModelWorksSection
    past_regression_runs: RunsSection
    what_drives_value: FeatureImportanceSection
    faq: FAQSection
