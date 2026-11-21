# P3 · Désaméricanisation conjointe sur Eurex

L’étude P3 contient les observations de marché, une famille de modèles qui satisfait les cotations américaines, une enveloppe extérieure de tous les vecteurs européens compatibles sous les hypothèses précisées et deux calculs liés à Dupire. Les commandes ci-dessous s’exécutent depuis la racine du dépôt. Python 3.10 ou plus récent suffit pour rejouer le certificat distribué.

## Télécharger les données et lancer le calcul

Depuis la racine du dépôt, exécuter cette commande PowerShell pour reproduire la coupe du **20 novembre 2026 à 12 h 00 min 50 s UTC**.

```powershell
python .\p3\p3_eurex.py pipeline --cache .\p3_cache --out .\runs\p3
```

Au premier lancement en ligne, la commande demande à Euronext le fichier parisien des transactions sur dérivés actions et indices de la séance précédente. Elle vérifie le SHA-256 du CSV décompressé. Elle télécharge aussi les originaux Eurex, Xetra, ESMA, BCE et DILA consignés dans le manifeste. Un cache complet occupe environ 420 Mio. Les lancements suivants réutilisent les fichiers après contrôle de leur empreinte.

Le rejeu écrit l’extrait `FIRDS.xml` en UTF-8 avec une fin de ligne LF après la déclaration XML sur toutes les plateformes. Il compare ensuite le fichier octet par octet à la référence publiée.

Sous Windows, le client Python utilise CryptoAPI pour valider la chaîne du serveur. Le module `truststore` 0.10.5 est livré dans `p3_vendor` et fonctionne directement dans le venv. Pour les redirections à courte durée de vie de Deutsche Börse, le pipeline utilise le `curl.exe` système de Windows lorsqu'il est disponible. Un échec de validation indique l'adresse concernée, y compris après redirection. [Documentation de truststore](https://truststore.readthedocs.io/en/stable/) · [curl fourni avec Windows](https://curl.se/windows/microsoft.html)

Si le réseau utilise une autorité de certification privée, le fichier PEM fourni par l'administrateur peut être sélectionné pour cette session PowerShell. Remplacer le chemin ci-dessous par celui du fichier reçu.

```powershell
$env:P3_CA_BUNDLE = 'C:\certificats\autorites-approuvees.pem'
python .\p3\p3_eurex.py pipeline --cache .\p3_cache --out .\runs\p3
```

| Entrée | Utilisation dans le calcul |
|---|---|
| Carnets Eurex et Xetra, références ESMA, €STR de la BCE et dividende documenté auprès de la DILA | Reconstruction du panel TOTB et vérification des trois diffusions sur les 20 fourchettes américaines |
| Transactions Euronext Paris, MIC XMON, et références ESMA de la même séance | Rapprochement par ISIN parisien, sous-jacent, échéance, strike, sens, style, livraison et multiplicateur. Les prix de transaction servent au contrôle de marché. |

Le fichier Euronext contient **46 037** messages. Le rapprochement des référentiels identifie **10** séries parisiennes aux caractéristiques recherchées. **8** transactions portent sur **6** de ces séries et satisfont les filtres à la coupe. Les heures de transaction et de publication doivent toutes deux précéder ou égaler la coupe. Le CSV de sortie conserve les deux ISIN et les deux horodatages. Le fichier de transactions, sa notice de réutilisation et les conventions de l'étude sont référencés dans [RIGHTS_SOURCES.md](RIGHTS_SOURCES.md).

À la fin de `pipeline`, le terminal affiche les témoins communs, les bornes du quotient de Dupire, la volatilité ponctuelle au point demandé et les prix européens des 20 contrats.

Pour afficher les résultats d’une exécution terminée, lancer la commande suivante. Elle suit le pointeur `latest.json` puis lit les résultats enregistrés dans ce run.

```powershell
python .\p3\p3_eurex.py results --out .\runs\p3 --format text
```

L'option `--run CHEMIN` sélectionne directement un dossier d'exécution. En cas de redirection, `pipeline` et `results` produisent un objet JSON. L'option `--format text` conserve le tableau lors d'une redirection et `--format json` affiche le JSON en console. La section `results` contient `joint`, `pointwise` et les lignes de `european_bounds`. Les nouveaux fichiers `pipeline.json` incluent la même section. Les prix américains certifiés pour chaque couple modèle–contrat se trouvent dans `pointwise/american_prices.csv`.

Le relevé `pipeline.json` indique l'origine effective de chaque lot. Si le service Eurex a retiré un fichier éphémère, le pipeline reprend son extrait vérifié. Si l'URL Euronext renvoie une séance plus récente ou une réponse HTTP 404/410, il reprend le ZIP original du 20 novembre inclus sous `data/euronext`. Une révision de la séance cible, une empreinte invalide du téléchargement ou une erreur réseau persistante interrompt l'analyse. L'exécution publie son dossier de résultats après validation.

| Variante | Commande depuis la racine |
|---|---|
| Exiger les 28 originaux issus des services ou du cache, sans repli sur les données distribuées | `python .\p3\p3_eurex.py pipeline --require-originals` |
| Rejouer sans connexion avec le cache et les données datées du dépôt | `python .\p3\p3_eurex.py pipeline --offline` |
| Vérifier les seuls originaux d'un cache complet sans connexion | `python .\p3\p3_eurex.py pipeline --offline --require-originals` |
| Télécharger puis réoptimiser les paramètres des trois diffusions avec NumPy et SciPy | `python .\p3\p3_eurex.py pointwise-fit --download --out .\runs\p3-fit` |

`pointwise --download` active aussi l'acquisition et accepte les options habituelles de choix du point. `pipeline` prend par défaut le niveau de l'action à 78 EUR à la première échéance. Chaque dossier réussi contient le panel transmis au calcul, les bornes européennes, les prix américains vérifiés, le certificat ponctuel et les transactions rapprochées.

## Volatilité locale ponctuelle

Le calcul calibre une diffusion à un facteur sur les 20 spreads et vérifie les prix américains en temps continu. À la première échéance, pour une action à 78 EUR, deux diffusions compatibles ont exactement les mêmes prix avec des volatilités de 15 % et 45 %. Le modèle de référence donne 25,02710 %. Pour la famille explicitement restreinte à une vitesse de variance affine et au facteur spatial du certificat, la borne extérieure est de 23,136334 % à 25,617386 %. La preuve, les unités, les autres hypothèses de régularité et les commandes figurent dans [POINTWISE.md](POINTWISE.md).

```powershell
python .\p3\p3_eurex.py pointwise --coordinate stock --level 78 --sigma 0.15 --sigma 0.45
```

## Vérifier depuis la racine du dépôt

```powershell
python .\p3\p3_eurex.py verify
python -m unittest discover -s .\p3 -p test_p3.py
```

La première commande reconstruit les cotations à partir des extraits des fournisseurs, vérifie leurs empreintes, recalcule les prix et contrôle les certificats ainsi que les fichiers de résultats. Elle fonctionne hors ligne. Pour contrôler aussi la page 53 du rapport financier original auprès de la DILA, utiliser Poppler ou installer pypdf.

```powershell
python -m pip install -r requirements-review.txt
python .\p3\p3_eurex.py verify --official-dividend
```

## Séance et périmètre

| Élément | Observation ou convention |
|---|---|
| Horodatage de coupe | 20 novembre 2026 à 12 h 00 min 50 s UTC |
| Action | TotalEnergies SE, FR0000120271, carnet Xetra segment XETB, 78,45 à 78,51 EUR |
| Contrats | Eurex XEUR, TOTB standard, livraison physique de 100 actions, prix par action en EUR |
| Sélection | Cinq strikes pairs les plus proches du milieu du carnet spot, 74, 76, 78, 80 et 82. Un call et un put à chacun des strikes, aux échéances du 18 décembre 2026 et du 15 janvier 2027 |
| Fraîcheur | Dernier état de carnet publié ou mis à jour au plus tard à la coupe, seuil de 15 s. Âge maximal des 20 états Eurex retenus de 7,041603412 s |
| Transactions facultatives | 95 messages de transactions EUR, sans indicateur de correction, sur ces 20 ISIN publiés avant la coupe. La dernière transaction remonte à 11 h 49 min 08 s UTC |
| Taux | €STR du 19 novembre, publié le 20, 2,441 % annualisés. Actualisation simple ACT/360 à taux constant |
| Dividende | 0,90 EUR brut par action ordinaire, décidé le 22 juillet 2026, annoncé le 23 juillet. Détachement le 31 décembre 2026, paiement de la ligne européenne le 5 janvier 2027 |
| Règlement | Prime à T+1 et action ou strike à T+2 selon le calendrier d’échange explicité dans la méthode. Les cotations et les résultats CSV utilisent la même unité de prime |

La séance fournit 185 références FIRDS actives satisfaisant les filtres de produit et d’échéance. Le test conjoint impose les 20 observations du panel. Les deux marchés publient des horodatages distincts. L’interprétation de calibration suppose que ces derniers carnets restent représentatifs à la coupe et qu’une même action ordinaire est livrable. Le taux, le calendrier, les dividendes bruts, l’absence de coûts de financement spécifiques et le modèle sans friction font partie du certificat.

## Résultats reproductibles

Les 47 témoins explicites reproduisent simultanément les 20 fourchettes américaines. Les trois premiers engendrent un ensemble convexe entier de vecteurs européens réalisables, avec une politique d’exercice admissible commune par contrat. La marge du premier témoin jusqu’au bord de fourchette le plus proche dépasse 0,06499 EUR par action. La table conserve aussi les témoins qui atteignent les deux extrêmes calculés pour chaque instrument.

| Janvier 2027, strike 78 | Bid–ask américain | Américain du premier témoin | Européen du même témoin | Enveloppe extérieure européenne |
|---|---|---:|---:|---|
| Call | 3,06 à 3,32 | 3,12500 | 2,98254 | 2,63926742 à 3,07753597 |
| Put | 2,86 à 3,17 | 3,10500 | 3,10500 | 2,79172739 à 3,17000000 |

L’écart européen call moins put à ce strike doit être compris entre −0,15245998 et −0,09246403 EUR. Les bornes de parité exactes, avant arrondi d’affichage, sont atteintes par les deux témoins qui utilisent les bords du carnet spot. En combinant le call à environ 3,04744 d’un témoin et le put à environ 2,84833 d’un autre, on obtiendrait +0,19911 EUR. Ce calcul montre précisément la dépendance perdue par des conversions séparées.

Au strike 78 du processus de gains actualisés, l’espérance de l’accroissement du temps local entre les deux échéances appartient à [0,45031324, 2,03663920] dans les modèles continus considérés. Le quotient de Dupire en différences finies avec un espacement de 4 est encadré par [0,01315423, 0,07774606] en variance annualisée. Sa définition et celle du processus de gains figurent dans [METHOD.md](METHOD.md).

## Fichiers

| Fichier | Utilité |
|---|---|
| `data/panel.json`, `data/trades.csv` | Entrées de calibration et transactions de contrôle |
| `data/evidence/`, `data/sources.json` | Extraits des fournisseurs, dates, identifiants, URL et SHA-256 des 27 originaux |
| `data/euronext/` | Original Euronext Paris daté, empreintes du ZIP et du CSV, notice du fournisseur et références parisiennes extraites de FIRDS |
| `certified/acquisition.json` | Relevé de l'exécution en ligne partie d'un cache vide, avec acquisition des 28 fichiers et contrôle de la coupe |
| `certified/european_bounds.csv` | Une ligne par contrat avec son prix européen témoin, son prix américain, ses bornes et l’écart aux valeurs effectivement atteintes |
| `certified/outer.json` | Système conjoint de contraintes linéaires rationnelles et projection affine vers tout le vecteur européen |
| `certified/certificate.json` | Lois de transition rationnelles, famille intérieure, politiques et multiplicateurs duaux |
| `certified/summary.json` | Résumé de référence régénéré par le vérificateur |
| [RIGHTS_SOURCES.md](RIGHTS_SOURCES.md) | Origine, transformations et conditions de réutilisation de chaque source |

Les bornes extérieures du CSV sont arrondies vers l’extérieur à huit décimales. Les prix des témoins sont arrondis au plus proche. Les fractions et les preuves permettent un calcul exact.

## Recalculer et expérimenter

Le recalcul des propositions de témoins ou d’un nouveau portefeuille utilise NumPy et SciPy. La vérification avec `verify` utilise la bibliothèque standard. Une version différente de HiGHS peut proposer d’autres modèles tout aussi vérifiables.

```powershell
python -m pip install -r requirements-review.txt
python .\p3\p3_eurex.py certify --out .\runs\p3-eurex
python .\p3\p3_eurex.py verify --certificate .\runs\p3-eurex\certificate.json
python .\p3\p3_eurex.py portfolio --weights DE000F4E4YY7=1 --weights DE000F4E4YZ4=-1
python .\p3\p3_eurex.py div-risk --amount-lo 0.85 --amount-hi 0.95
```

La dernière commande teste un scénario de sensibilité autour du montant déclaré, à dates inchangées. Le même témoin reste compatible avec les 20 cotations pour **tout** montant entre 0,85 et 0,95 EUR. La marge restante garantie atteint au moins 0,01514532 EUR. Les options `--ex-lo`, `--ex-hi`, `--pay-lo`, `--pay-hi` acceptent des dates ISO pour tester l’incertitude de calendrier.

Pour traiter une autre coupe, `certify --panel MON_PANEL.json --center K --spacing H --out SORTIE` accepte le format de `data/panel.json`. Fournir deux échéances, les fourchettes, un taux en pourcentage, un seul sous-jacent EUR, les dividendes discrets, et les listes exhaustives de dates ISO `calendar.exercise_days` et `calendar.settlement_days` jusqu’au règlement de la dernière échéance. Les horizons et calendriers du panel fourni sont intégrés. Les montants du panel personnalisé sont des chaînes décimales ou rationnelles. Le solveur de témoins peut échouer sur un autre panel. Un tel échec laisse ouverte la faisabilité générale.

## Rejouer l’acquisition

La commande `pipeline` ci-dessus enchaîne l'acquisition et l'analyse. La commande suivante est réservée au rejeu des 27 originaux du lot Eurex/Xetra et de ses sources auxiliaires.

Depuis un cache contenant les originaux du manifeste, la commande suivante relit les archives FIRDS, reconstruit les extraits des carnets et contrôle les fichiers de taux et de dividende.

```powershell
python .\p3\p3_eurex.py replay-originals --cache .\p3_cache --out .\p3_replay --download
```

Les fichiers minute de Deutsche Börse ont une fenêtre de rétention courte. Chaque minute peut être conservée pendant la fenêtre officielle par `capture-minute --utc AAAA-MM-JJTHH:MM --out DOSSIER`. Pour une minute expirée, utiliser des originaux archivés pour `replay-originals` ou vérifier le panel livré avec `verify`. Les fichiers sous `data/evidence` assurent la reproduction hors ligne sur ce panel après expiration.
