"""
Bot Leboncoin - motos cross (achat / revente)
Repère les nouvelles annonces, estime la marge et :
  - écrit annonces.json (affiché par index.html sur ton téléphone)
  - envoie les bonnes affaires sur Discord

Install :  pip install lbc requests
Local   :  python3 botcross.py          (boucle)
GitHub  :  python3 botcross.py --once   (1 passage)
"""
import json, os, random, re, sys, time
from datetime import datetime
from statistics import median
import requests
import lbc

# ========== CONFIG ==========
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
RECHERCHES = ["moto cross", "quad"]   # une recherche par mot-clé
PRIX_MIN, PRIX_MAX = 500, 4000
VILLE = lbc.City(lat=50.72, lng=3.16, radius=80_000, city="Neuville-en-Ferrain")
INTERVALLE_MIN = 15
CYLINDREES = {"85", "125", "250", "450"}   # cylindrées gardées (motos)
QUADS = {"raptor": "Yamaha Raptor", "banshee": "Yamaha Banshee", "yfz": "Yamaha YFZ",
         "ltz": "Suzuki LTZ", "ltr": "Suzuki LTR", "trx": "Honda TRX",
         "kfx": "Kawasaki KFX", "ds ?450": "Can-Am DS"}   # quads sportifs gardés

FRAIS_DIVERS = 100            # essence, déplacement, mise en avant de l'annonce...
DECOTE_REVENTE = 0.97         # on revend un peu sous le marché pour vendre vite
REPARATIONS_BASE = 50         # petit budget par défaut (graissage, réglages)
REPARATIONS = {               # mot trouvé dans l'annonce -> coût estimé (€)
    "à réviser": 150, "a reviser": 150, "révision à prévoir": 150,
    "embrayage": 120, "pneu": 100, "kit chaine": 80, "kit chaîne": 80,
    "joint spi": 60, "fourche": 150, "plastique": 120, "haut moteur": 350,
    "piston": 300, "ne démarre": 400, "ne demarre": 400, "fuite": 80,
}
MOTS_EXCLUS = ["pour pièces", "pour pieces", "hs", "épave", "recherche", "pit bike",
               "pocket", "quad enfant", "sans papiers"]
MARGE_DISCORD = 150           # marge mini pour une notif Discord
MIN_ECHANTILLONS = 3          # nb de prix vus avant d'estimer un prix de marché
FICHIER_VUES = "annonces_vues.json"
FICHIER_HISTO = "historique_prix.json"
FICHIER_SITE = "annonces.json"
# ============================

MARQUES = {"ktm": "KTM", "yamaha": "Yamaha", "yz": "Yamaha", "honda": "Honda",
           "crf": "Honda", "kawasaki": "Kawasaki", "kx": "Kawasaki", "suzuki": "Suzuki",
           "rmz": "Suzuki", "husqvarna": "Husqvarna", "gasgas": "GasGas",
           "gas gas": "GasGas", "beta": "Beta", "sherco": "Sherco", "tm": "TM"}
RE_CC = re.compile(r"(?<!\d)(50|65|85|105|125|144|150|250|300|350|400|450|660|700)(?!\d)")
RE_ANNEE = re.compile(r"\b(19[89]\d|20[0-3]\d)\b")
CAT = getattr(lbc.Category, "VEHICULES_MOTOS", None)


def lire(f, defaut):
    if os.path.exists(f):
        with open(f, encoding="utf-8") as fh:
            return json.load(fh)
    return defaut


def ecrire(f, data):
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def modele(texte):
    """Retourne 'KTM 85' ou 'Yamaha Raptor 700' par ex., ou None si on ne reconnaît pas."""
    cc = RE_CC.search(texte)
    quad = next((v for k, v in QUADS.items() if re.search(rf"\b{k}", texte)), None)
    if quad:
        return f"{quad} {cc.group(1)}" if cc else quad
    marque = next((v for k, v in MARQUES.items() if re.search(rf"\b{k}(?![a-z])", texte)), None)
    if not (marque and cc and cc.group(1) in CYLINDREES):
        return None
    return f"{marque} {cc.group(1)}"


def analyser(ad, histo):
    titre = ad.subject or ""
    texte = (titre + " " + (getattr(ad, "body", "") or "")).lower()
    if any(m in texte for m in MOTS_EXCLUS) or not ad.price:
        return None
    mod = modele(texte)
    if not mod:
        return None
    prix = int(ad.price)
    histo.setdefault(mod, []).append(prix)
    histo[mod] = histo[mod][-60:]          # on garde les 60 derniers prix vus

    if len(histo[mod]) < MIN_ECHANTILLONS:
        return None                        # pas assez de données pour estimer
    marche = int(median(histo[mod]))
    repa = REPARATIONS_BASE + sum(c for m, c in REPARATIONS.items() if m in texte)
    revente = int(marche * DECOTE_REVENTE)
    marge = revente - prix - repa - FRAIS_DIVERS
    annee = RE_ANNEE.search(texte)
    return {
        "id": str(getattr(ad, "id", ad.url)), "titre": titre, "modele": mod,
        "annee": annee.group(1) if annee else None, "prix": prix, "marche": marche,
        "reparations": repa, "revente": revente, "frais": FRAIS_DIVERS,
        "marge": marge, "url": ad.url, "date": datetime.now().isoformat(timespec="minutes"),
    }


def envoyer_discord(a):
    if not DISCORD_WEBHOOK:
        return
    couleur = 0x3FB950 if a["marge"] >= 300 else 0xD29922
    champs = [("Prix de marché estimé", a["marche"]), ("Budget réparations", a["reparations"]),
              ("Revente estimée", a["revente"]), ("Frais divers", a["frais"])]
    embed = {
        "title": f"🔔 {a['titre']}", "url": a["url"], "color": couleur,
        "description": f"## {a['prix']:,} €".replace(",", " "),
        "fields": [{"name": n, "value": f"{v} €", "inline": True} for n, v in champs]
                  + [{"name": "Marge potentielle", "value": f"**+{a['marge']} €**"}],
    }
    requests.post(DISCORD_WEBHOOK, json={"embeds": [embed]}, timeout=10)


def passage(client, vues, histo, site, init=False):
    ads = []
    for recherche in RECHERCHES:
        params = dict(text=recherche, locations=[VILLE], limit=35, sort=lbc.Sort.NEWEST,
                      ad_type=lbc.AdType.OFFER, price=[PRIX_MIN, PRIX_MAX])
        if CAT:
            params["category"] = CAT
        ads += client.search(**params).ads
        time.sleep(random.uniform(2, 5))   # petite pause entre deux recherches
    nouvelles = 0
    for ad in ads:
        ad_id = str(getattr(ad, "id", ad.url))
        if ad_id in vues:
            continue
        vues.add(ad_id)
        a = analyser(ad, histo)
        if a and not init:
            site.insert(0, a)
            nouvelles += 1
            if a["marge"] >= MARGE_DISCORD:
                envoyer_discord(a)
    del site[100:]                         # 100 annonces max sur la page
    ecrire(FICHIER_VUES, list(vues)[-2000:])
    ecrire(FICHIER_HISTO, histo)
    ecrire(FICHIER_SITE, site)
    print(f"[{time.strftime('%H:%M')}] {len(ads)} lues, {nouvelles} ajoutées")


def main():
    client = lbc.Client()
    vues, histo, site = set(lire(FICHIER_VUES, [])), lire(FICHIER_HISTO, {}), lire(FICHIER_SITE, [])
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and DISCORD_WEBHOOK:
        requests.post(DISCORD_WEBHOOK, timeout=10,
                      json={"content": "✅ Bot Cross : test OK, les notifications marchent !"})
    while True:
        try:
            passage(client, vues, histo, site, init=not vues)
        except Exception as e:
            print("Erreur :", e)
        if "--once" in sys.argv:
            break
        time.sleep(INTERVALLE_MIN * 60 + random.randint(0, 90))


if __name__ == "__main__":
    main()
