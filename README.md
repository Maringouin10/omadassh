# Omada ER605 (SSH) pour Home Assistant

Intégration Home Assistant qui lit l'état d'un routeur **TP-Link Omada ER605**
(testé sur la v2.30, firmware 2.4.5) **directement en SSH**, sans contrôleur
Omada, sans cloud et sans SNMP.

L'intégration est **en lecture seule** : elle n'exécute que des commandes
`show …` (et `ping`) et ne modifie jamais la configuration du routeur.

## Ce que vous obtenez

| Entité | Source sur le routeur | Détail |
|---|---|---|
| `sensor.er605_clients_connectes` | `show arp` | Nombre d'appareils sur le LAN, liste (IP/MAC) en attribut |
| `sensor.er605_passerelle_wan` | `show arp` (interface `vlan4094`) | IP de la passerelle du FAI (MAC en attribut) |
| `binary_sensor.er605_internet` | `ping` lancé par le routeur | Connexion Internet OK / coupée |
| `sensor.er605_latence_internet` | `ping` | Latence moyenne en ms |
| `sensor.er605_perte_de_paquets_internet` | `ping` | Perte de paquets en % |
| `sensor.er605_dernier_demarrage` | `show system-info` | Date du dernier redémarrage (uptime) |
| `sensor.er605_firmware` | `show system-info` | Version du firmware |
| `sensor.er605_version_materielle` | `show system-info` | Désactivé par défaut |
| `device_tracker.omada_ssh_xx_xx_…` | `show arp` | Un tracker « à la maison / absent » par appareil |

Les noms exacts des entités dépendent de la langue de votre Home Assistant.

### Limites connues

* **Pas de débit (Mbit/s) ni de compteurs de trafic** : la CLI de l'ER605 ne
  les expose pas lorsque le routeur est adopté par un contrôleur ou par l'app
  Omada. Il faudra SNMP pour ça (prévu dans une prochaine version).
* **Pas de CPU ni de RAM** : `show system-info` ne les donne pas.
* **Présence basée sur la table ARP** : un appareil reste dans la table ARP
  quelques minutes après son départ. Le délai « absent » est réglable
  (3 minutes par défaut). Les téléphones en veille peuvent disparaître du Wi-Fi :
  augmentez le délai si nécessaire.
* **Ping** : le format de sortie de la commande `ping` de l'ER605 n'a pas encore
  été vérifié sur un vrai routeur. Si le routeur ne sait pas l'exécuter,
  les entités Internet deviennent simplement « indisponibles » et le reste
  continue de fonctionner.

## Prérequis sur le routeur

1. SSH activé (c'est le cas par défaut : `show ssh configuration` →
   `ssh server: on`).
2. Un compte administrateur du routeur (le même que pour l'interface web).
3. Home Assistant doit pouvoir joindre le routeur sur le port 22
   (même réseau, par exemple `192.168.0.1`).

Le message *« This gateway is being managed by Controller »* n'est pas un
problème : après `enable`, les commandes nécessaires restent disponibles.

## Installation avec HACS

1. HACS → menu ⋮ → **Dépôts personnalisés**.
2. Ajoutez `https://github.com/maringouin10/omadassh`, catégorie **Intégration**.
3. Installez **Omada ER605 (SSH)** puis redémarrez Home Assistant.

### Installation manuelle

Copiez le dossier `custom_components/omada_ssh` dans le dossier
`config/custom_components/` de Home Assistant, puis redémarrez.

## Configuration

**Paramètres → Appareils et services → Ajouter une intégration → Omada ER605 (SSH)**

| Champ | Par défaut |
|---|---|
| Hôte | `192.168.0.1` |
| Port | `22` |
| Nom d'utilisateur | `admin` |
| Mot de passe | — |

Options (bouton **Configurer** de l'intégration) :

| Option | Par défaut | Rôle |
|---|---|---|
| Intervalle de mise à jour | 30 s | Fréquence d'interrogation du routeur (minimum 10 s) |
| Délai avant absence | 180 s | Temps pendant lequel un appareil reste « à la maison » après avoir disparu de la table ARP |
| Cible du ping | `8.8.8.8` | Adresse pinguée par le routeur. Laisser vide pour désactiver |

## Fonctionnement

L'ER605 n'accepte pas de commande passée directement à `ssh` : il n'offre
qu'une CLI interactive. L'intégration ouvre donc un shell, attend l'invite `>`,
tape `enable` pour obtenir l'invite `#`, puis envoie les commandes une par une.
La session SSH est conservée entre deux mises à jour et rouverte
automatiquement si elle est coupée.

## Dépannage

Activez les journaux détaillés dans `configuration.yaml` :

```yaml
logger:
  default: warning
  logs:
    custom_components.omada_ssh: debug
```

## Développement

```bash
pip install -r requirements_test.txt
pytest
```

Les tests utilisent de vraies sorties de l'ER605 (`tests/fixtures`) et un faux
serveur SSH qui reproduit la CLI du routeur.
