# One-off / maintenance: apply French header_tips + header_alerts into fr.yaml
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FR = ROOT / "configs" / "strings" / "fr.yaml"

FR_TIPS = {
    "startup_message": "Astuce · Place le curseur dans Word, Gmail, Slack… puis appuie sur Alt+T",
    "tips": [
        "Astuce · Appuie sur Alt+Q ou clique sur l'avatar dans la barre latérale pour arrêter l'enregistrement",
        "Astuce · Alt+T reste gratuit — transcription rapide, sans LLM",
        "Astuce · Sélectionne du texte, Alt+I, et dis ce que tu veux changer",
        "Astuce · Appuie sur Alt+M n'importe où pour dicter un e-mail entier",
        "Astuce · Alt+A garde la conversation en mémoire — pose des questions de suite",
        "Astuce · Bruit ambiant = pas d'arrêt auto ? Appuie sur Alt+Q pour arrêter",
        "Astuce · Sélectionne un paragraphe → Alt+P — ton et grammaire en une fois",
        "Astuce · Alt+C dans le terminal : décris ce qu'il te faut en langage courant",
        "Astuce · Alt+L : sélectionne du texte et demande une traduction vers n'importe quelle langue",
        "Astuce · Alt+D : dicte un message direct pour WhatsApp, Slack, Discord, SMS",
        "Astuce · Alt+X : crée une publication ou une réponse pour LinkedIn, X, YouTube, Reddit",
        "Astuce · Colle des notes de réunion, sélectionne-les, Alt+S pour un résumé court",
        "Astuce · Sélectionne un texte brouillon, Alt+I, dis « raccourcis ça » — terminé",
        "Astuce · Alt+V à Alt+N = tes prompts perso. Édite-les dans Prompts",
        "Astuce · Crée un prompt perso pour répondre aux commentaires au ton de ta marque",
        "Astuce · Marre de retaper les mêmes prompts IA ? Fais un générateur en prompt perso",
        "Astuce · Idée prompt perso : transformer des notes en post LinkedIn accrocheur",
        "Astuce · Utilise des prompts persos pour des prompts vidéo Kling/Runway formatés",
        "Astuce · Idée prompt perso : extraire actions et échéances d'un texte",
        "Astuce · Alt+H : pose-moi des questions sur PerkySue dans l'onglet Aide",
        "Pro · Si Smart Focus n'a pas collé, copie la sortie depuis l'onglet Console",
        "Astuce · Pour quitter l'étape Écoute : clic sur l'avatar ou Alt+Q",
        "Astuce · Change d'app pendant que PerkySue réfléchit — le résultat arrive là où tu as lancé",
        "Astuce · Smart Focus : tu lances, tu fais autre chose, le texte arrive au bon endroit",
        "Astuce · CPU ? Whisper small (rapide) ou medium (précis). ⚙️ → Modèle STT",
        "Astuce · Bruit ambiant ? L'enregistrement ne s'arrête pas tout seul — Alt+Q ou clic sur l'avatar",
        "Astuce · Édite le prompt de chaque mode dans Prompts — adapte PerkySue à toi",
        "Astuce · Whisper se trompe sur un mot ? Ajoute-le aux mots-clés STT dans Prompts",
    ],
    "delay_before_first_ms": 3500,
    "display_ms": 7500,
    "delay_between_ms": 15000,
}

FR_ALERTS = {
    "critical": {
        "no_llm": "Aucun LLM détecté. Télécharge-en un dans Paramètres.",
        "save_restart": "Tu dois enregistrer et redémarrer PerkySue",
        "shortcut_in_use": "Ce raccourci est déjà utilisé ({other_name}). Choisis-en un autre.",
        "llm_error_400": "Erreur LLM (400) — contexte trop grand ? Augmente « Entrée max » dans Paramètres.",
        "llm_error_generic": "Erreur LLM — regarde la console. Augmente « Entrée max » (contexte) dans Paramètres si tu utilises Alt+A.",
        "max_input_reached": "Limite max d'entrée atteinte — l'historique a été réduit.",
        "max_input_context_reached": "Limite d'entrée (contexte) ({max_input}) atteinte. Essaie d'augmenter à {suggested} dans Paramètres → Performance.",
        "max_output_tokens_reached": "Limite de sortie ({max_output}) atteinte. Monte à {suggested} dans Paramètres → Performance.",
        "llm_request_timeout": "Requête LLM expirée — essaie un délai de 180 s ou 240 s dans Paramètres → Performance.",
    },
    "regular": {
        "recording_stopped": "🛑 Enregistrement arrêté",
        "processing_stopped": "🛑 Traitement arrêté",
        "recording_no_audio": "Aucun audio capturé — enregistrement arrêté ou vérifie le micro.",
        "recording_too_short": "Enregistrement trop court — pas de texte. Vérifie le micro ou parle plus longtemps.",
        "copied_to_clipboard": "Copié dans le presse-papiers",
        "llm_not_available": "Orchestrateur LLM indisponible.",
        "no_logs_to_save": "Aucun journal à enregistrer",
        "all_logs_copied": "Tous les journaux copiés dans le presse-papiers",
        "download_success": "✓ Téléchargement terminé.",
        "download_progress": "⏳ Téléchargement « {name} »… {pct} %",
    },
    "run_test_400_hint": "→ 400 Bad Request = souvent contexte trop grand pour le modèle. Augmente « Entrée max » dans Paramètres → Performance.",
    "run_test_timeout_hint": "→ Le modèle n'a pas fini à temps. Dans Paramètres → Performance, mets le délai requête LLM à 180 ou 240 s (selon ta machine).",
    "document_injection": {
        "llm_error_400": "Erreur LLM (400) — contexte trop grand ? Augmente « Entrée max » (contexte) dans Paramètres.",
        "llm_error_generic": "Erreur LLM — regarde la console. Augmente « Entrée max » (contexte) dans Paramètres.",
        "max_input_reached": "⚠️ Limite max d'entrée atteinte — l'historique a été réduit. Voir Paramètres → Entrée max et la capacité de ta machine.\n\n",
        "chat_max_input_reached": "⚠️ Tu as atteint la limite d'entrée (contexte) ({max_input}). Augmente « Entrée max » dans Paramètres → Performance à {suggested} ou plus.",
        "chat_context_limit_reached": "⚠️ Limite de contexte ({max_input}) atteinte — entrée et sortie partagent la même enveloppe. Augmente « Entrée max » dans Paramètres → Performance à {suggested} ou plus.",
        "chat_max_output_reached": "⚠️ Réponse tronquée : limite de sortie ({max_output}) atteinte. Augmente « Sortie max » dans Paramètres → Performance à {suggested} ou plus.",
        "chat_empty_reply": "— Réponse vide. Reformule ou regarde la console.",
    },
}


def main():
    text = FR.read_text(encoding="utf-8")
    marker = "# --- Header bar: tips rotation + alerts"
    if marker not in text:
        raise SystemExit("marker not found in fr.yaml")
    head = text[: text.index(marker)].rstrip()
    frag = yaml.dump(
        {"header_tips": FR_TIPS, "header_alerts": FR_ALERTS},
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    )
    out = head + "\n\n# --- Header bar: tips rotation + alerts (i18n; optional Data/Configs/*.yaml override) ---\n" + frag
    FR.write_text(out, encoding="utf-8")
    print("Wrote", FR)


if __name__ == "__main__":
    main()
