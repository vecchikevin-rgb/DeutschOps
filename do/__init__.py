"""DeutschOps — pipeline di apprendimento del tedesco A2 -> B1.

Struttura:
    do.base      fondamenta: path, config, client LLM, tracker, preflight, staging
    do.lezione   ingestione della lezione: audio, estrazione, Google Doc
    do.sapere    i DB cumulativi (vocaboli, grammatica, errori, registro)
    do.studio    il livello didattico: carte, frasi i+1, drill, TTS, esame
    do.uscite    i renderer PDF
    do.motore    stato, briefing, ponte verso il motore condiviso

Entry point unico: `deutschops.py` nella root.
"""

__version__ = "2.0.0-dev"
