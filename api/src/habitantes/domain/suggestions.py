"""Suggestion vocabulary shared by ingestion and the agent — no I/O.

Defines the 16 Kinds, their fixed parent Topics, and the Cluster entry (the unit
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
    TRAVEL_AND_TRANSPORT = "Travel & Transport"
    HOUSING_AND_CAF = "Housing & CAF"


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
    TRANSPORT = "Transport"  # airlines, trains, coaches, carpooling, car/bike rental
    HOUSING = "Housing"  # student residences, housing platforms, flatshare listings
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
    Kind.TRANSPORT: Topic.TRAVEL_AND_TRANSPORT,
    Kind.HOUSING: Topic.HOUSING_AND_CAF,
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
    Kind.TRANSPORT: (
        "transporte",
        "passagem",
        "voo",
        "avião",
        "trem",
        "ônibus",
        "carona",
        "aluguel de carro",
        "bicicleta",
        "tram",
    ),
    Kind.HOUSING: (
        "moradia",
        "alojamento",
        "residência",
        "apartamento",
        "aluguel",
        "colocation",
        "estúdio",
    ),
    Kind.OTHER: (),
}


# Subcategories per Kind, defined by the maintainer after studying the real groups
# (docs/SUGGESTIONS_QUALITY_DIAGNOSIS.md). One primary subcategory per business; the
# one-line definitions are shown to the extraction LLM so it can tell them apart.
# Kinds absent here (Housing) have no subcategories.
SUBCATEGORY_GUIDE: dict[Kind, tuple[tuple[str, str], ...]] = {
    Kind.RESTAURANTS_AND_BARS: (
        (
            "Comida Brasileira",
            "restaurantes, lanchonetes e pratos de culinária brasileira (rodízio, feijoada, açaí, coxinha)",
        ),
        (
            "Internacionais",
            "cozinhas que não são brasileira nem francesa: japonesa e asiática, italiana e pizza, mexicana, indiana, libanesa, tacos, kebab",
        ),
        (
            "Franceses",
            "restaurantes franceses e regionais: brasserie, bouillon, fondue, raclette, crêperie",
        ),
        ("Bares e Pubs", "bares, pubs e cervejarias onde se vai beber"),
        (
            "Cafés e Lanchonetes",
            "cafés, padarias, doceria, fast food e lanchonetes (também onde se trabalha tomando café)",
        ),
        (
            "Casas Noturnas e Eventos",
            "baladas, casas de show, música ao vivo, festas e eventos",
        ),
        ("Outros", "restaurante universitário (CROUS/RU) e o que não cabe nas outras"),
    ),
    Kind.SHOPS: (
        (
            "Casa e Decoração",
            "móveis, utilidades, decoração, loja de 2 euros (Ikea, Action, Gifi, Hema)",
        ),
        (
            "Eletrônicos",
            "eletrônicos, informática, celulares e assistência técnica de aparelhos (Fnac, Boulanger, LDLC, Back Market)",
        ),
        (
            "Vestuário e Usados",
            "roupas, calçados, malas e acessórios; brechós e lojas de segunda mão (H&M, Primark, La Remise)",
        ),
        (
            "Esporte e Lazer",
            "artigos esportivos, instrumentos musicais, livros e lazer (Decathlon, Go Sport)",
        ),
        (
            "Saúde e Beleza",
            "perfumaria, cosméticos, ótica e produtos de saúde (Sephora, Krys)",
        ),
        (
            "Bricolagem",
            "materiais de construção, ferramentas, jardinagem (Leroy Merlin, Bricorama)",
        ),
        (
            "Serviços e Impressão",
            "impressão, cópias, encadernação, papelaria, chaveiro, lavanderia, envio de encomendas",
        ),
        ("Outros", "o que não cabe nas outras"),
    ),
    Kind.PRODUCTS: (
        (
            "Alimentos e Bebidas",
            "alimentos, bebidas e marcas de mercearia (Yoki, guaraná, queijos, cachaça)",
        ),
        (
            "Saúde e Beleza",
            "medicamentos, suplementos, cosméticos, higiene (Doliprane, whey, Natura)",
        ),
        (
            "Eletrônicos e Tecnologia",
            "aparelhos, software e serviços digitais de marca",
        ),
        (
            "Casa, Vestuário e Esporte",
            "utensílios, roupas, calçados, equipamentos esportivos de marca (Tefal, Havaianas, Rossignol)",
        ),
        ("Outros", "livros, música, veículos e o que não cabe nas outras"),
    ),
    Kind.PLACES_AND_OUTINGS: (
        (
            "Montanhas e Natureza",
            "estações de esqui, montanhas, lagos, parques, trilhas, passeios ao ar livre",
        ),
        (
            "Cultura e Lazer",
            "cinema, museus, eventos, festivais, shows e atrações de lazer",
        ),
        (
            "Bairros e Moradia",
            "bairros, ruas e residências de Grenoble (onde morar, como é a vizinhança)",
        ),
        (
            "Cidades Vizinhas e Viagens",
            "cidades e comunas vizinhas de Grenoble (Meylan, Échirolles, Saint-Martin-d'Hères) e destinos de viagem (Lyon, Annecy, Genebra, países)",
        ),
        (
            "Outros",
            "comércio e centros comerciais (Grand Place), instituições (bibliotecas, universidades, prefeitura) e o que não cabe nas outras",
        ),
    ),
    Kind.PROFESSIONAL_SERVICES: (
        (
            "Documentos e Imigração",
            "advogados, prefeitura, consulado, visto, tradução de documentos, cartório",
        ),
        ("Financeiros e Seguros", "seguros, bancos, câmbio, remessas, contabilidade"),
        (
            "Emprego e Carreira",
            "empresas, vagas, agências de emprego, estágio, plataformas de trabalho",
        ),
        (
            "Serviços Residenciais",
            "limpeza, reparos, mudança, eletricista, encanador, correios e entregas",
        ),
        ("Outros", "fotografia, informática, serviços diversos"),
    ),
    Kind.OTHER: (
        (
            "Contas e Utilidades",
            "bancos, seguros, energia, água, telecom, operadoras, internet",
        ),
        (
            "Governo e Administrativo",
            "serviços públicos, consulados, administração, associações",
        ),
        (
            "Mídia e Compras Online",
            "canais de TV, jornais, streaming, sites e apps de compra",
        ),
        ("Outros", "o que não cabe nas outras"),
    ),
    Kind.DOCTORS: (
        (
            "Hospitais e Urgência",
            "hospitais, CHU, clínicas, pronto atendimento e médico de plantão 24h (SOS Médecins, Médecins 7/7)",
        ),
        (
            "Consultórios e Especialistas",
            "médico generalista e especialistas em consultório: pediatra, ginecologista, dermatologista, oftalmologista, psicólogo, fisioterapeuta, osteopata",
        ),
        ("Exames e Farmácias", "laboratórios, exames, testes e farmácias"),
        (
            "Plataformas e Outros",
            "plataformas de consulta online, ótica e o que não cabe nas outras",
        ),
    ),
    Kind.MARKETS_AND_GROCERIES: (
        (
            "Supermercados",
            "grandes redes de supermercado (Carrefour, Lidl, Auchan, Leclerc, Géant Casino)",
        ),
        (
            "Mercados Especializados",
            "lojas latinas, africanas, asiáticas, portuguesas, orgânicas/bio, de conveniência e congelados (Nosso, Tienda Latina, Biocoop, Picard)",
        ),
        (
            "Feiras e Açougues",
            "feiras e mercados abertos, açougues, peixarias, padarias de bairro",
        ),
        ("Outros", "o que não cabe nas outras"),
    ),
    Kind.COURSES_AND_TEACHERS: (
        ("Idiomas", "cursos e professores de francês e de outros idiomas"),
        (
            "Universidades e Formação",
            "universidades, escolas, formações profissionais e cursos acadêmicos",
        ),
        ("Aulas Práticas e Hobbies", "dança, música, autoescola, esporte, artes"),
    ),
    Kind.GYMS_AND_SPORTS: (
        ("Academias", "academias de musculação e ginástica, fitness"),
        (
            "Esportes Individuais e Outdoor",
            "natação, escalada, crossfit, corrida, tênis, ioga, esqui",
        ),
        (
            "Esportes Coletivos e Combate",
            "futebol, basquete, vôlei, artes marciais, luta",
        ),
    ),
    Kind.SALONS_AND_BEAUTY: (
        ("Cabelo", "cabeleireiro, coiffure, barbearia, coloração, corte"),
        (
            "Estética",
            "unhas, depilação, cílios, sobrancelha, limpeza de pele, massagem",
        ),
        ("Tatuagem e Piercing", "estúdios de tatuagem e piercing"),
    ),
    Kind.DENTISTS: (
        ("Clínica Geral", "dentista generalista, limpeza, consultas de rotina"),
        (
            "Especialidades e Urgência",
            "ortodontia, cirurgia oral, odontopediatria, urgência odontológica",
        ),
    ),
    Kind.TRANSLATORS: (
        ("Tradução Juramentada", "tradutores juramentados / traduction assermentée"),
        (
            "Outras Traduções",
            "tradução simples, de documentos específicos ou outros idiomas",
        ),
    ),
    Kind.VETS_AND_PETS: (
        ("Clínicas Veterinárias", "veterinários e clínicas para animais"),
        ("Adoção e Resgate", "adoção, abrigos, resgate de animais"),
        (
            "Cuidado e Adestramento",
            "tosa, creche, hotel para pets, adestramento, pet shop",
        ),
    ),
    Kind.TRANSPORT: (
        (
            "Aéreo",
            "companhias aéreas e voos (Air France, TAP, LATAM, Gol, Azul, Iberia, KLM, Lufthansa, Ryanair, easyJet, Volotea)",
        ),
        (
            "Trem e Ônibus",
            "trens e ônibus de longa distância (SNCF, TGV, TER, Ouigo, FlixBus, blablabus, Transaltitude)",
        ),
        (
            "Local, Aluguel e Carona",
            "transporte urbano (tram, ônibus urbano, TAG), aluguel de carro ou bicicleta (Getaround, Citiz, Ouicar, Metrovelo), carona e aplicativos (BlaBlaCar, Bolt)",
        ),
    ),
}
KIND_SUBCATEGORIES: dict[Kind, tuple[str, ...]] = {
    k: tuple(name for name, _ in v) for k, v in SUBCATEGORY_GUIDE.items()
}


def valid_subcategory(kind: Kind | str, name: str | None) -> bool:
    """True when `name` is one of the Kind's subcategories."""
    return name is not None and name in KIND_SUBCATEGORIES.get(Kind(kind), ())


def subcategory_guide_text(kind: Kind | str) -> str:
    """Bullet list "name: definition" of a Kind's subcategories (empty for Housing)."""
    return "\n".join(f"  - {n}: {d}" for n, d in SUBCATEGORY_GUIDE.get(Kind(kind), ()))


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
