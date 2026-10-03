"""Suggestion vocabulary shared by ingestion and the agent — no I/O.

Defines the 14 Kinds, their fixed parent Topics, and the Cluster entry (the unit
stored in the Suggestions Qdrant collection). Cluster entries deliberately carry
no author, member-name or phone field: models forbid unknown fields, so such data
cannot be smuggled into the collection.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Topic(str, Enum):
    """Topics a Kind can sit under. Values equal the `en_name` in config categories."""

    FOOD_AND_RESTAURANTS = "Food & Restaurants"
    DAILY_LIFE_AND_SERVICES = "Daily Life & Services"
    HAIR_AND_BEAUTY = "Hair & Beauty"
    SPORTS_AND_ACTIVITIES = "Sports & Activities"
    HEALTH_AND_INSURANCE = "Health & Insurance"
    DOCUMENTS_AND_BUREAUCRACY = "Documents & Bureaucracy"
    INTEGRATION_AND_LANGUAGE = "Integration & Language"
    PETS_AND_ANIMALS = "Pets & Animals"
    SKI_AND_TREKKING = "Ski & Trekking"


class Kind(str, Enum):
    RESTAURANTS_AND_BARS = "Restaurants & Bars"
    MARKETS_AND_GROCERIES = "Markets & Groceries"
    SHOPS = "Shops"
    PRODUCTS = "Products"
    SALONS_AND_BEAUTY = "Salons & Beauty"
    GYMS_AND_SPORTS = "Gyms & Sports"
    DOCTORS = "Doctors"
    DENTISTS = "Dentists"
    TRANSLATORS = "Translators"
    PROFESSIONAL_SERVICES = "Professional Services"
    COURSES_AND_TEACHERS = "Courses & Teachers"
    VETS_AND_PETS = "Vets & Pets"
    PLACES_AND_OUTINGS = "Places & Outings"
    OTHER = "Other"


KIND_TOPIC: dict[Kind, Topic] = {
    Kind.RESTAURANTS_AND_BARS: Topic.FOOD_AND_RESTAURANTS,
    Kind.MARKETS_AND_GROCERIES: Topic.FOOD_AND_RESTAURANTS,
    Kind.SHOPS: Topic.DAILY_LIFE_AND_SERVICES,
    Kind.PRODUCTS: Topic.DAILY_LIFE_AND_SERVICES,
    Kind.PROFESSIONAL_SERVICES: Topic.DAILY_LIFE_AND_SERVICES,
    Kind.OTHER: Topic.DAILY_LIFE_AND_SERVICES,
    Kind.SALONS_AND_BEAUTY: Topic.HAIR_AND_BEAUTY,
    Kind.GYMS_AND_SPORTS: Topic.SPORTS_AND_ACTIVITIES,
    Kind.DOCTORS: Topic.HEALTH_AND_INSURANCE,
    Kind.DENTISTS: Topic.HEALTH_AND_INSURANCE,
    Kind.TRANSLATORS: Topic.DOCUMENTS_AND_BUREAUCRACY,
    Kind.COURSES_AND_TEACHERS: Topic.INTEGRATION_AND_LANGUAGE,
    Kind.VETS_AND_PETS: Topic.PETS_AND_ANIMALS,
    Kind.PLACES_AND_OUTINGS: Topic.SKI_AND_TREKKING,
}


# Portuguese words a user (or a member) uses for each Kind. Embedded with every
# Cluster so a query naming the category ("dentista", "academia") matches it, and
# used by search to infer a Kind filter from the query.
KIND_KEYWORDS_PT: dict[Kind, tuple[str, ...]] = {
    Kind.RESTAURANTS_AND_BARS: (
        "restaurante",
        "bar",
        "pizzaria",
        "padaria",
        "café",
        "sushi",
        "rodízio",
        "lanchonete",
        "cervejaria",
        "comer",
        "almoçar",
        "jantar",
    ),
    Kind.MARKETS_AND_GROCERIES: (
        "mercado",
        "supermercado",
        "feira",
        "mercearia",
        "açougue",
        "comprar comida",
        "alimentos",
        "ingredientes",
        "frutas",
        "verduras",
        "legumes",
    ),
    Kind.SHOPS: (
        "loja",
        "comprar",
        "eletrônicos",
        "eletrodomésticos",
        "roupas",
        "móveis",
        "ferramentas",
        "ótica",
        "armarinho",
        "brechó",
    ),
    Kind.PRODUCTS: ("produto", "marca", "comprar", "onde encontrar"),
    Kind.SALONS_AND_BEAUTY: (
        "cabeleireiro",
        "cabeleireira",
        "salão",
        "barbeiro",
        "manicure",
        "estética",
        "tatuagem",
        "tatuador",
        "piercing",
        "depilação",
        "maquiagem",
    ),
    Kind.GYMS_AND_SPORTS: (
        "academia",
        "ginástica",
        "esporte",
        "natação",
        "yoga",
        "musculação",
    ),
    Kind.DOCTORS: (
        "médico",
        "médica",
        "pediatra",
        "ginecologista",
        "dermatologista",
        "oftalmologista",
        "clínico geral",
        "psicólogo",
        "fisioterapeuta",
        "consulta",
    ),
    Kind.DENTISTS: ("dentista", "ortodontista", "odontologia", "dente"),
    Kind.TRANSLATORS: (
        "tradutor",
        "tradutora",
        "tradução",
        "juramentado",
        "intérprete",
    ),
    Kind.PROFESSIONAL_SERVICES: (
        "contador",
        "advogado",
        "seguro",
        "mecânico",
        "oficina",
        "carro",
        "banco",
        "imobiliária",
        "mudança",
        "eletricista",
        "encanador",
        "serviço",
    ),
    Kind.COURSES_AND_TEACHERS: (
        "curso",
        "professor",
        "professora",
        "aula",
        "escola",
        "idioma",
    ),
    Kind.VETS_AND_PETS: (
        "veterinário",
        "veterinária",
        "pet",
        "cachorro",
        "gato",
        "animal",
    ),
    Kind.PLACES_AND_OUTINGS: (
        "passeio",
        "lugar",
        "trilha",
        "viagem",
        "parque",
        "esqui",
    ),
    Kind.OTHER: (),
}


def topic_for_kind(kind: Kind | str) -> Topic:
    """Fixed parent Topic of a Kind (accepts the Kind or its string value)."""
    return KIND_TOPIC[Kind(kind)]


class ClusterMember(BaseModel):
    """One Suggestion inside a Cluster (one line per name+Kind)."""

    model_config = ConfigDict(extra="forbid")

    name: str  # business/place/product name (never a person)
    thumbs_up: int = Field(0, ge=0)
    thumbs_down: int = Field(0, ge=0)
    last_date: date
    items: list[str] = []
    community_business: bool = False


class ClusterEntry(BaseModel):
    """A Cluster: the unit stored (one point) in the Suggestions collection.

    `topic` is derived from `kind`; if given it must match. `members` holds every
    Suggestion; only `summary` is limited to the top picks.
    """

    model_config = ConfigDict(extra="forbid")

    topic: Topic | None = None
    kind: Kind
    label: str
    thumbs_up: int = Field(0, ge=0)
    thumbs_down: int = Field(0, ge=0)
    last_date: date
    members: list[ClusterMember]
    summary: str

    @model_validator(mode="after")
    def _topic_follows_kind(self) -> "ClusterEntry":
        expected = KIND_TOPIC[self.kind]
        if self.topic is None:
            self.topic = expected
        elif self.topic != expected:
            raise ValueError(f"Kind {self.kind.value!r} belongs to {expected.value!r}")
        return self
