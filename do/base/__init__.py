"""Fondamenta: percorsi, configurazione, client LLM, e i tre moduli maturi
portati dalla v1 (tracker, preflight, staging).

I tre moduli portati NON sono stati riscritti a intuito: sono le uniche parti
del progetto con una logica di fallimento pensata, nata da guasti reali. Le
loro invarianti sono documentate in cima a ciascun file e vanno conservate.
"""
