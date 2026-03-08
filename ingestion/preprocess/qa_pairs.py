from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


# ── Logging ──────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


# ── Scoring patterns (compiled once) ─────────────────────────────────────────
OUTDATED_PATTERN = re.compile(
    r"\b(covid|corona(v[ií]rus)?|pcr|ant[ií]gen(o)?|pass sanitaire|passe sanitaire|"
    r"attestation|confinement|couvre[- ]feu|quarenten(a|e)|vaccin(a|e)[cç][aã]o|"
    r"fronti[eè]re|restri[cç][aã]o(s)? de viagem|test(e)? de pcr|isolement)\b",
    re.IGNORECASE,
)

UNCERTAIN_PATTERN = re.compile(
    r"\b(n[aã]o sei|sei l[aá]|acho|talvez|provavelmente|n[aã]o tenho certeza|"
    r"n[aã]o lembro|posso estar enganad[oa]|pelo que eu saiba)\b",
    re.IGNORECASE,
)

ACTIONABLE_PATTERN = re.compile(
    r"\b(voc[eê] (precisa|tem que|deve)|basta|[eé] s[oó] |faz assim|passo a passo|"
    r"primeiro|depois|em seguida|liga|manda email|envia|agenda|preenche|anexa|"
    r"entra no site|vai precisar)\b",
    re.IGNORECASE,
)

OFFICIAL_DOMAIN_PATTERN = re.compile(
    r"(service-public\.fr|\.gouv\.fr|ameli\.fr|caf\.fr|urssaf\.fr|etudiant\.gouv\.fr|"
    r"campusfrance\.org|ofii\.fr|legifrance\.gouv\.fr)",
    re.IGNORECASE,
)

URL_PATTERN = re.compile(r"(https?://|www\.)", re.IGNORECASE)
LIST_STRUCTURE_PATTERN = re.compile(r"(^|\n)\s*(\d+[\).\s-]|[-•]\s+)", re.MULTILINE)


# ── Topics ───────────────────────────────────────────────────────────────────
TOPIC_KEYWORDS = {
    "Visa & Residency": r"(visto|visa|titre de s[eé]jour|tds|r[eé]c[eé]piss[eé]|recepisse|pr[eé]fecture|ofii|passeport talent|nationalit[eé]|naturaliz|carte de s[eé]jour|renouvellement|s[eé]jour|autorisation de travail|demande de titre|rdv pr[eé]fecture|anef|isso)",
    "Banking & Finance": r"(banco|conta bancária|boursorama|lydia|iban|transfer[eê]ncia|cartão|cart[aã]o de cr[eé]dito|imposto|declaraç[aã]o de renda|salário|pix|câmbio|n26|revolut|wise|société générale|crédit agricole|hello bank|fortuneo|orange bank|chèque|virement|prélèvement|timbre fiscal)",
    "Housing & CAF": r"(caf|aide au logement|apl|aluguel|apartamento|quarto|logement|loyer|coloc|caution|garant|visale|hlm|bail|contrat de location|prime d.activit[eé]|résidence|imóvel|alugar|proprietaire|agence imobili)",
    "Health & Insurance": r"(s[eé]curit[eé] sociale|cpam|mutuelle|smerra|assurance maladie|m[eé]decin|carte vitale|ameli|reembolso|hospital|rem[eé]dio|consulta|dentist|ordonnance|m[eé]dico|pharmacie|généraliste|m[eé]decin traitant|óculos|100.sant[eé]|prise en charge|urgence|sos m[eé]decin|samu|samu 15|medecin de garde)",
    "University & Studies": r"(universidade|curso|crous|mestrado|doutorado|tese|dissertaç[aã]o|bolsa|idex|capes|cnpq|campus france|faculdade|licence|master|doctorat|bourse|inscriç[aã]o|matrícula|aulas|professor|uga|grenoble alpes|inpg|Sciences Po|école|instituto)",
    "Work & Internship": r"(est[aá]gio|estagio|emprego|contrato de trabalho|trabalhar|cdi|cdd|stage |candidatura|vaga|salaire|fiche de paie|urssaf|siret|autoentrepreneur|micro.entrepreneur|recrutamento|entrevista|cv |linkedIn|pole emploi|france travail|ch[oô]mage|are )",
    "Documents & Bureaucracy": r"(tradu[cç][aã]o|cart[oó]rio|certid[aã]o|apostila|cpf|consulado|consulat|procura[cç][aã]o|notaire|l[eé]galisa|reconhecimento de firma|atestado|comprovante|declaraç[aã]o|formulário|rg |passaporte|casier judiciaire|extrait)",
    "Daily Life & Services": r"(telefone|sim card|free mobile|orange|sfr|bouygues|supermercado|amazon|leboncoin|delivery|electricit[eé]|internet fixo|box |edf|gaz |serviço|preço|loja|compras|laundry|lavanderia|correios|la poste|tabac|mairie)",
    "Travel & Transport": r"(trem|train|sncf|blablacar|[oô]nibus|passagem|viagem|bagagem|ryanair|easyjet|metro|v[éê]lo|bicicleta|aeroporto|voo|embarcar|fronteira|schengen|attestation de d[eé]placement|flixbus|ouigo|tgv|covoiturage|permis de conduire|cnh)",
    "Integration & Language": r"(franc[eê]s|idioma|l[íi]ngua|cours de fran[cç]ais|b1|b2|c1|delf|dalf|tcf|integraç[aã]o|cultura|costumes|adaptaç[aã]o|alliance française|babbel|duolingo|cours de langue|aulas de franc[eê]s)",
    "Ski & Trekking": r"(ski|esqui|piste|pista (azul|verde|vermelha|noire|rouge|bleue)|station de ski|forfait|remontée|téléski|téléphérique|huez|alpe d.huez|2 alpes|deux alpes|chamrousse|belledonne|vercors|chartreuse|trilha|rando|randonnee|raquette|snowboard|snow|neve|montanha|randonnée|sommet|refuge|col de porte|visiorando|komoot|ign)",
    "Food & Restaurants": r"(restaurante brasileiro|comida brasileira|farofa|guaran[aá]|tapioca|feij[aã]o|arroz|coxinha|pão de queijo|açaí|mercado portugu[eê]s|nosso |nosso supermercado)",
    "Sports & Activities": r"(futebol|fut |basquete|v[oô]lei|natação|piscina|academia\b|musculação|badminton|escalada|climbing|patinaç[aã]o|yoga\b|pilates|corrida\b|running|academia ao ar livre|grupo de esporte|grupo de (fut|v[oô]lei|basquete|nataç[aã]o|corrida)|treino|treinar|parceiro de esporte|esportivo)",
    "Nightlife & Events": r"(festa\b|balada|happy hour|evento\b|show ao vivo|concerto|festival\b|samba\b|pagode|forr[oó]\b|m[uú]sica ao vivo|noitada|barzinho|danceteria|ingresso|entrada pro (festival|show|evento)|quem vai no evento|programaç[aã]o cultural|f[eê]te|spectacle|soirée|o[uù] sortir)",
    "Neighbourhood & Safety": r"(bairro\b|perigoso|tranquilo para morar|corenc|echirolles|saint.martin.d.h[eè]res|seyssinet|meylan|crolles|grenoble.[eé].seguro|quartier|morar em grenoble|regi[aã]o (boa|segura|tranquila)|vizinhança|barulhento|calmo para morar|qual bairro|onde morar|mapa de onde n[aã]o morar)",
    "Marketplace & Buy/Sell": r"(vendendo\b|vendo \b|preciso vender|disponível para venda|disponivel\b|leboncoin|doaç[aã]o\b|doando\b|troco\b|usado\b|segunda.m[aã]o|algu[eé]m vendendo|algu[eé]m tem para vender|dar de graça|quem quiser ficar com|procuro comprar|compro\b|aceito doaç[aã]o)",
    "Hair & Beauty": r"(cabeleireiro|sal[aã]o de cabelo|corte de cabelo|cabelo cacheado|barbeiro|coiffeur|coiffure|manicure|pedicure|sobrancelha|colorir cabelo|tingir cabelo|depilaç[aã]o|sal[aã]o barato|cabelo em grenoble|m[aá]scara hidratante|produto para cabelo)",
    "Pets & Animals": r"(cachorro\b|gato\b|\bpet\b|animal de estimaç[aã]o|veterin[aá]rio|veterinaire|clinique v[eé]t[eé]r|animaux domestiques|passear com cachorro|raç[aã]o para|vacina (animal|pet|cachorro|gato)|pet.friendly|dog.friendly|hotelzinho|cuidar de cachorro|dog walker)|petshop",
    "Phone & Telecom": r"(plano de celular|forfait (mobile|t[eé]l[eé]phone)|sim card\b|chip de celular|linha (francesa|francesa)|n[uú]mero franc[eê]s|free mobile|bouygues\b|sfr\b|troca de celular|celular usado|tela quebrada|conserto de celular|desbloqueio|desbloq|smartphone usado)",
}


def score_qa(answer_msgs: List[Dict[str, Any]], confirmed: bool) -> int:
    if not answer_msgs:
        return 0

    text = "\n".join(str(m.get("message", "")) for m in answer_msgs).strip()
    tl = text.lower()
    n_chars = len(text)
    n_urls = len(URL_PATTERN.findall(text))
    unique_users = len(
        {m.get("user") for m in answer_msgs if m.get("user") is not None}
    )

    sc = 10

    # Length
    if n_chars < 30:
        sc -= 15
    else:
        sc += min(n_chars / 600.0, 1.0) * 20

    # Links / evidence
    if n_urls >= 1:
        sc += 10
    if n_urls >= 2:
        sc += 5
    if OFFICIAL_DOMAIN_PATTERN.search(text):
        sc += 10

    # Actionable
    if ACTIONABLE_PATTERN.search(text):
        sc += 15

    # Structure
    if LIST_STRUCTURE_PATTERN.search(text) or re.search(
        r"\b(passo a passo|1\)|2\)|3\))\b", tl
    ):
        sc += 10

    # Multiple answerers
    if unique_users >= 2:
        sc += 6
    if unique_users >= 3:
        sc += 4

    # Confirmation
    if confirmed:
        sc += 15

    # Uncertainty penalty
    uncertain_hits = len(UNCERTAIN_PATTERN.findall(text))
    if uncertain_hits >= 1:
        sc -= min(uncertain_hits * 6, 18)

    # Outdated penalty
    if OUTDATED_PATTERN.search(text):
        sc -= 25

    # Freshness (small bump)
    year = answer_msgs[-1]["timestamp"].year
    if year >= 2024:
        sc += 8
    elif year >= 2023:
        sc += 5
    elif year >= 2022:
        sc += 2

    sc = max(0, min(100, sc))
    return int(round(sc))


def extract_context(
    classified_msgs: List[Dict[str, Any]], q_index: int, context_window: int
) -> Dict[str, Any]:
    start = max(0, q_index - context_window)
    preceding = [
        m
        for m in classified_msgs[start:q_index]
        if m["type"] not in ("noise",) and len(str(m["message"]).strip()) > 10
    ]

    window_text = " ".join(str(m["message"]) for m in preceding).lower()
    window_text += " " + str(classified_msgs[q_index]["message"]).lower()

    best_topic, best_count = "General", 0
    for topic, pattern in TOPIC_KEYWORDS.items():
        count = len(re.findall(pattern, window_text))
        if count > best_count:
            best_topic, best_count = topic, count

    return {
        "context_messages": [
            {"user": m["user"], "message": str(m["message"])[:200]} for m in preceding
        ],
        "topic": best_topic,
    }


def detect_threads(df: pd.DataFrame, thread_gap_h: int) -> List[pd.DataFrame]:
    threads: List[pd.DataFrame] = []
    current_rows: List[pd.Series] = []

    for _, row in df.iterrows():
        if not current_rows:
            current_rows.append(row)
            continue

        gap = (row["timestamp"] - current_rows[-1]["timestamp"]).total_seconds()
        if gap > thread_gap_h * 3600:
            if len(current_rows) >= 2:
                threads.append(pd.DataFrame(current_rows))
            current_rows = [row]
        else:
            current_rows.append(row)

    if len(current_rows) >= 2:
        threads.append(pd.DataFrame(current_rows))

    return threads


def extract_qa_pairs(
    input_csv: Path,
    thread_gap_h: int,
    answer_window_h: int,
    context_window: int,
    tier_high: int,
    tier_medium: int,
) -> List[Dict[str, Any]]:
    df = pd.read_csv(input_csv, parse_dates=["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["message"] = df["message"].fillna("")

    if "source_file" not in df.columns:
        df["source_file"] = input_csv.name

    logger.info("Loaded %s messages from %s", f"{len(df):,}", input_csv.name)

    threads = detect_threads(df, thread_gap_h)
    logger.info("Threads detected: %s", f"{len(threads):,}")

    qa_pairs: List[Dict[str, Any]] = []

    for tid, thread_df in enumerate(threads):
        msgs = thread_df.to_dict(orient="records")

        # In this refactored version, we assume msg_type is already present
        # from the extraction step.
        if "msg_type" not in thread_df.columns:
            logger.warning("msg_type column missing in %s", input_csv.name)
            continue

        classified: List[Dict[str, Any]] = []
        for m in msgs:
            row = dict(m)
            row["type"] = m.get("msg_type")
            classified.append(row)

        # For each question find answers within window
        for q_i, q_msg in enumerate(classified):
            if q_msg["type"] != "question":
                continue

            q_user = q_msg["user"]
            q_time = q_msg["timestamp"]
            clarifications, answers, confirmations = [], [], []

            for m in classified[q_i + 1 :]:
                if (m["timestamp"] - q_time).total_seconds() > answer_window_h * 3600:
                    break

                t, u = m["type"], m["user"]
                if t == "clarification" and u == q_user:
                    clarifications.append(m)
                elif t == "answer" and u != q_user:
                    answers.append(m)
                elif t == "confirmation" and u == q_user:
                    confirmations.append(m)
                elif t == "question" and u != q_user:
                    break  # new topic

            if not answers:
                continue

            q_text = str(q_msg["message"])
            if clarifications:
                q_text += " " + " ".join(str(c["message"]) for c in clarifications)

            confirmed = len(confirmations) > 0
            sc = score_qa(answers, confirmed)

            tier = (
                "high" if sc >= tier_high else "medium" if sc >= tier_medium else "low"
            )
            ctx = extract_context(classified, q_i, context_window)

            qa_pairs.append(
                {
                    "source_file": q_msg.get("source_file"),
                    "thread_id": tid,
                    "thread_start": str(classified[0]["timestamp"]),
                    "topic": ctx["topic"],
                    "context": ctx["context_messages"],
                    "question": q_text.strip(),
                    "question_user": q_user,
                    "question_time": str(q_time),
                    "answer": "\n".join(str(a["message"]) for a in answers).strip(),
                    "answer_users": list({a["user"] for a in answers}),
                    "n_answers": len(answers),
                    "n_clarifications": len(clarifications),
                    "confirmed": confirmed,
                    "score": sc,
                    "tier": tier,
                }
            )

    return qa_pairs


def save_outputs(qa_pairs: list[dict], out_json: Path, out_csv: Path) -> None:
    # Save full outputs
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(qa_pairs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(qa_pairs).to_csv(out_csv, index=False)
    logger.info("Saved → %s", out_json)
    logger.info("Saved → %s", out_csv)

    # Save tier-split outputs
    df = pd.DataFrame(qa_pairs)

    # If empty, still create empty tier files (optional)
    tiers = ["high", "medium", "low"]
    for tier in tiers:
        tier_df = df[df["tier"] == tier].reset_index(drop=True)

        tier_json = out_json.with_name(out_json.stem + f"-{tier}" + out_json.suffix)
        tier_csv = out_csv.with_name(out_csv.stem + f"-{tier}" + out_csv.suffix)

        tier_json.write_text(
            json.dumps(tier_df.to_dict(orient="records"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tier_df.to_csv(tier_csv, index=False)

        logger.info("Saved → %s (%s rows)", tier_json, f"{len(tier_df):,}")
        logger.info("Saved → %s (%s rows)", tier_csv, f"{len(tier_df):,}")


def run_qa_builder(
    input_csv: Path,
    output_dir: Path,
    thread_gap_h: int,
    answer_window_h: int,
    context_window: int,
    tier_high: int,
    tier_medium: int,
) -> Path:
    """
    Input:  classified.csv
    Output: qa_pairs.json (in output_dir)
    """
    out_json = output_dir / "qa_pairs.json"
    out_csv = output_dir / "qa_pairs.csv"

    qa_pairs = extract_qa_pairs(
        input_csv, thread_gap_h, answer_window_h, context_window, tier_high, tier_medium
    )
    save_outputs(qa_pairs, out_json, out_csv)
    return out_json
