# Volatilité locale ponctuelle sur les options Eurex TotalEnergies

Sur la coupe du 20 novembre 2026, un même vecteur de 20 prix américains est compatible avec **toute volatilité annualisée finie positive ou nulle** au point choisi. La preuve part d’une diffusion scalaire calibrée sur chaque bid–ask. Elle construit des diffusions qui changent la volatilité sur un voisinage du point et conservent exactement les prix américains et européens du modèle de référence. Les données, les prix par contrat, les budgets numériques et les preuves sont inclus.

## Au premier terme, le 18 décembre 2026 à 19 h UTC

Les deux colonnes fixent le niveau 78 dans deux coordonnées distinctes. $M$ est le gain total actualisé. $S$ est le prix de livraison de l’action, dans la convention spot T+2 du panel. Les pourcentages sont annualisés en ACT/365F. Les bornes affichées dans la table sont arrondies vers l’extérieur.

| Résultat | Action $S=78$ EUR | Gains $M=78$ EUR |
|---|---:|---:|
| Ensemble exact, diffusions lisses sans limite commune de vitesse de variation | $[0,+\infty)$ | $[0,+\infty)$ |
| Diffusion de référence optimisée, valeur arrondie | 25,02710 % | 24,97292 % |
| Deux autres diffusions affines compatibles, valeurs arrondies | 23,69832 % et 25,42443 % | 23,64701 % et 25,36938 % |
| Enveloppe extérieure si la vitesse de variance est affine, avec le facteur spatial spécifié ci-dessous | [23,136334 %, 25,617386 %] | [23,086242 %, 25,561922 %] |
| Enveloppe extérieure si cette vitesse a une constante de Lipschitz au plus égale à 0,02 EUR²/jour², avec le même facteur spatial | [21,728612 %, 28,735045 %] | [21,681567 %, 28,672832 %] |

Dans la famille affine, les trois diffusions ont chacune leurs propres prix dans les 20 fourchettes. Leurs marges minimales garanties sont 0,02673735 EUR pour la référence, 0,00181236 EUR pour le témoin de volatilité basse et 0,00170155 EUR pour le témoin de volatilité haute. Les extrémités de l’enveloppe extérieure sont des bornes. L’ajustement directionnel fournit des valeurs effectivement atteintes. Le fichier `certified_pointwise/american_prices.csv` donne les 60 vérifications en euros par action.

## Rejouer le résultat

Exécuter les commandes depuis la racine du dépôt. Python 3.10 ou plus récent suffit à la vérification hors ligne.

Pour télécharger les données de la séance et vérifier la volatilité sur le panel reconstruit, utiliser `python .\p3\p3_eurex.py pipeline`. Les origines, les variantes de rejeu et les fichiers de sortie sont détaillés dans le [README](README.md).

~~~powershell
python .\p3\p3_eurex.py pointwise --coordinate stock --level 78 --sigma 0.15 --sigma 0.45
python .\p3\p3_eurex.py pointwise
python -m unittest discover -s .\p3 -p "test_*.py"
~~~

La première commande produit deux témoins dont les volatilités ponctuelles valent 15 % et 45 % pour l’action. La seconde utilise les gains actualisés, ce qui reprend la coordonnée du précédent calcul Dupire. `affine_speed_volatility_pct_outer` est l’enveloppe conditionnelle. `affine_speed_attained_volatility_pct` donne les valeurs atteintes, sous forme de paires arrondies vers l’extérieur. `minimum_margin_eur` est la distance garantie entre le prix américain d’un modèle et le bord du spread le plus proche, erreurs déjà déduites.

`--at` accepte un instant ISO avec fuseau, strictement entre la coupe et la dernière échéance. `--level` sélectionne un autre état avec $M\ge12$. La coordonnée action emploie un jour d’exercice et un instant distinct du changement de date. `--sigma` est répétable et exprimé en fraction annuelle. `--slope-limit` remplace l’exemple de constante 0,02. Un champ `lipschitz_speed_volatility_pct_outer` nul au format JSON indique que les conditions sur les variances intégrées excluent la valeur de cette constante. Le certificat de prix est réutilisable pour ces différents points.

Pour refaire l’optimisation et vérifier son résultat dans un nouveau dossier, la recherche numérique utilise NumPy et SciPy.

~~~powershell
python -m pip install numpy scipy
python .\p3\p3_eurex.py pointwise-fit --out .\runs\p3-ponctuel
python .\p3\p3_eurex.py pointwise --certificate .\runs\p3-ponctuel\certificate.json --coordinate stock
~~~

La recherche SLSQP ajuste le spot prépayé, l’ordonnée et la pente de la vitesse de variance. Le premier objectif maximise la plus petite marge sur les bids et les asks. Les deux objectifs suivants diminuent puis augmentent la variance instantanée au point sous contrainte de marge. Il s’agit d’une recherche numérique de témoins. Le vérificateur évalue leurs prix avec les arrondis décrits plus bas. Les bornes extérieures parcourent toute la famille annoncée, y compris les paramètres extérieurs au domaine de recherche du solveur. Avec `--mesh 1/16` la recherche subdivise le pas jusqu’à 1/32 puis, si nécessaire, 1/64 lorsque le signe d’une marge reste indécidable. L’export exige des marges strictement positives. `--backend python` permet de vérifier les convolutions en arithmétique entière avec la seule bibliothèque standard.

## Diffusion calibrée, dividende et exercice

$t$ est le nombre de jours ACT écoulés depuis la coupe. Avec les facteurs d’actualisation $P$ du panel, soit $Q_d$ la valeur actuelle des dividendes déjà détachés et $L(d)$ la date de règlement à T+2 d’une livraison le jour $d$. Au cours d’une journée le modèle vérifie $P(L(d))S=M-Q_d$. Les seuils américains sont $H_i(d)=Q_d+K_iP(L(d))$. Le dividende brut déclaré est de 0,90 EUR, détaché le 31 décembre 2026 et payé le 5 janvier 2027. Le taux plat utilisé est l’€STR observé de 2,441 %. Le panel traite comme contemporains les carnets recevables à la coupe, selon les horodatages et la tolérance documentés. Les dates, le règlement, la fiscalité et le financement suivent [METHOD.md](METHOD.md).

Posons $h(s)=e^{-1/s}$ si $s>0$ et $h(s)=0$ sinon, $y=(x-1)/11$, puis $\beta(x)=h(y)/(h(y)+h(1-y))$. Ce facteur $C^\infty$ vaut zéro sous 1 EUR et un à partir de 12 EUR. Pour un spot prépayé $z$ dans le spread Xetra, la diffusion de référence vérifie

$$
dM_t=\beta(M_t)\sqrt{v(t)}\,dW_t,\qquad M_0=z,\qquad v(t)=a+bt>0.
$$

Les coefficients du témoin sont $z=78{,}44661451$, $a=1{,}34313504$ et $b=-0{,}010731649$. L’unité de $v$ est l’EUR²/jour. Le coefficient spatial est lipschitzien et borné. La solution forte est une vraie martingale, la barrière de 1 EUR garde l’action au-dessus de la réserve de dividende. Une densité positive au voisinage de 78 découle déjà des trajectoires qui restent au-dessus de 12 jusqu’au point d’observation, pour lesquelles la loi est celle d’un brownien absorbé à 12 avec horloge déterministe. Au point d’état $m$ dans la zone $\beta=1$, la volatilité relative annualisée est $\sqrt{365v(t)}/m$ pour $M$, et $\sqrt{365v(t)}/(m-Q_d)$ pour $S$.

La fenêtre d’exercice du contrat américain finit à 20 h CET un jour d’exercice, soit 19 h UTC sur cet horizon d’hiver. Si un détenteur exerce plus tôt le même jour, il peut différer sa décision à la dernière heure admissible de ce jour. Le seuil $H_i(d)$ est constant pendant la journée et le gain est convexe en la martingale $M$. L’inégalité de Jensen conditionnelle garantit une espérance au moins égale pour cette décision différée. L’enveloppe de Snell sur les **37 dates** traite ainsi tout l’exercice autorisé par ces conventions, y compris l’exercice précédant le dividende. [Spécification Eurex TotalEnergies](https://www.eurex.com/ex-en/markets/equ/equ-opt/options/TotalEnergies-947314).

## Ensemble identifié exact

Soit $t_*$ l’instant demandé. On construit un changement de temps déterministe $\phi$ qui fixe $t_*$, les deux bornes de valorisation, chaque fin d’exercice et chaque changement de date. Sa demi-fenêtre $\ell$ est le minimum de 30 minutes et de la moitié de la distance au repère distinct le plus proche. La largeur vaut une heure au point publié. Pour $0\le r\le1$, avec $u=(t-t_*)/\ell$, on pose

$$
B(u)=
\begin{cases}\exp[-u^4/(1-u^2)] & |u|<1,\\ 0& |u|\ge1,\end{cases}
\qquad
\phi(t)=t_*+\ell u[1-(1-r)B(u)] .
$$

La fonction coïncide avec l’identité hors de la fenêtre. Comme $uB'(u)\le0$ et $0\le B\le1$, sa dérivée est au moins $r$ et vaut exactement $r$ au centre. Pour $r>1$, on prend la fonction inverse de celle de paramètre $1/r$. Pour $r=0$, l’horloge reste strictement croissante. Sa dérivée vaut $5u^4+O(u^6)$ près du centre, avec facteur résiduel lisse strictement positif. Sa racine carrée est donc lisse aussi. Chaque coefficient construit est régulier dans le temps et dans l’état.

La diffusion $M_{\phi(t)}$ a pour coefficient en temps calendaire
$$
\beta(x)\sqrt{v(\phi(t))\phi'(t)} .
$$
Aux fins d’exercice, tous les noyaux de transition sont identiques à ceux du modèle initial. Les seuils du dividende et de livraison sont communs. La récurrence de Snell et les espérances terminales donnent donc **les mêmes prix exacts contrat par contrat**. La loi terminale entière est conservée à chacune des deux échéances, ce qui conserve aussi tous les strikes européens à ces deux termes.

Pour réaliser une volatilité annuelle $s$ quelconque au point, choisir $r=s^2d^2/(365v(t_*))$, avec $d=m$ en gains et $d=m-Q_d$ pour l’action. Les exemples $s=0$, $0{,}15$ et $0{,}45$ sont vérifiés en fractions exactes. La formule s’applique à tout réel fini $s\ge0$. Si la classe économique exige une volatilité strictement positive au point, l’ensemble devient $(0,+\infty)$. Cette preuve porte sur une classe autorisant ces changements de temps sans borne commune de dérivée. Elle conserve les **prix du modèle**, eux-mêmes certifiés à l’intérieur des spreads observés. Dès les deux exemples 15 % et 45 %, tout estimateur donnant une valeur unique sur cette chaîne a une erreur d’au moins 15 points de pourcentage dans l’un de ces deux modèles.

## Vérification des prix américains de la diffusion continue

Le noyau proposé à chaque intervalle remplace $\mathcal N(0,V_j)$ par une loi symétrique sur un réseau de pas $h=1/32$ EUR, avec des poids entiers de masse totale $2^{28}$. Ici $V_j=\int_{t_{j-1}}^{t_j}v(u)\,du$ est calculé en fractions exactes. Le prix numérique SLSQP est indépendant du calcul ci-dessous.

1. Le vérificateur encadre l’écart de prix du call entre le noyau et la gaussienne à **tout strike**. Aux nœuds il utilise l’expression normale du call. L’intégrale de la densité utilise Simpson composite, avec un reste majoré par $16 x d^4/2880$ pour une largeur de panneau $d$ en coordonnées standardisées sur $[0,x]$. Cette borne suit de $|\varphi^{(4)}|\le16$. La densité est encadrée par les séries alternées de l’exponentielle et de la formule de Machin pour $\pi$, en nombres entiers et fractions. Entre nœuds s’ajoute $h^2\varphi(0)/(8\sqrt{V_j})$, avec racine inférieure dans le code. Au-delà du support, la décroissance du call et la symétrie couvrent les deux queues.
2. Sur le modèle brownien arithmétique, chaque valeur de continuation est convexe, 1-lipschitzienne et monotone dans le sens du contrat. Sa dérivée seconde positive a masse totale au plus un. L’écart pour tout tel payoff est donc borné par l’écart uniforme des calls, via leur représentation intégrale et l’égalité des moyennes. Le maximum avec le gain immédiat et l’espérance préservent la borne cumulative par récurrence. Le Snell discret est calculé sur tous les états atteignables du réseau. Payoffs et continuations sont arrondis en unités de $2^{-22}$ EUR et l’erreur totale de cet arrondi est au plus le nombre d’étapes augmenté d’un, en ces unités.
3. On couple la diffusion positive et le brownien arithmétique par le même bruit jusqu’à la première atteinte de 12. Avec $V=\int_0^T v(t)dt$ et $x=(z-12)^2/(2V)$, la réflexion du brownien donne $p_{\rm hit}\le\min(1,2(1+x/256)^{-256})$. L’isométrie d’Itô puis l’inégalité maximale $L^2$ de Doob donnent $\mathbb E\sup_{t\le T}|M_t-B^z_{V(t)}|\le2\sqrt{Vp_{\rm hit}}$ sous le couplage. L’inégalité s’applique à toute politique d’exercice et donc au prix optimal. Les deux modèles peuvent être évalués dans la filtration brownienne commune, où leurs valeurs de continuation dépendent de l’état.
4. La division par le facteur de règlement de la prime reconvertit le résultat en euros par action. Pour le témoin de référence, le budget gaussien maximal est inférieur à 0,001654 EUR, le budget de localisation à 0,000000507 EUR et l’arrondi monétaire à 0,0000091 EUR. Les colonnes du CSV donnent ces trois budgets séparément. Le contrôle final exige que l’intervalle entier de prix se trouve dans le spread de chaque option.

## Bornes utilisant une hypothèse quantitative

Pour le facteur $\beta$ indiqué plus haut et toute vitesse positive déterministe, le prix européen d’un modèle ne dépend, à une échéance donnée, que de $z$ et du temps de variance cumulé $V(T)=\int_0^T v(s)ds$. En temps de variance, $dX=\beta(X)dW$. La convexité du gain et la propriété de martingale rendent le prix européen croissant au sens large en $V$.

Les preuves duales du P3 fournissent des bornes européennes tirées conjointement des prix américains. Pour chacune des deux échéances, un call ou un put permet d’exclure tous les $V\ge96$ EUR², en comparant sa borne supérieure à un prix plancher rigoureux au temps de variance 96. La preuve emploie le couplage précédent uniformément sur le bid–ask du spot. Elle divise ensuite ce bid–ask en huit intervalles. Pour chaque sous-intervalle et chaque maturité, deux inégalités de prix vanille encadrent $V_1$ et $V_2$ en respectant le sens de monotonie en spot de chaque contrat. Les ISIN, les extrémités rationnelles et les huit paires figurent dans `operational_variance_proof`. Les contraintes du solveur de recherche des témoins n’interviennent pas dans ces exclusions.

Si $v(t)=a+bt$, les deux valeurs intégrées donnent
$$
v(t)=(1-w)\frac{V_1}{T_1}+w\frac{V_2}{T_2},\qquad w=\frac{2t-T_1}{T_2-T_1}.
$$
L’évaluation sur les boîtes certifiées tient compte du signe des poids. Pour une vitesse de constante de Lipschitz $L$, l’écart de $v(t)$ à la vitesse moyenne sur $[u,w]$ est au plus $L\int_u^w|s-t|ds/(w-u)$. On effectue l’intersection des contraintes sur $[0,T_1]$, $[T_1,T_2]$ et $[0,T_2]$ avant de réunir les sous-intervalles de spot. La limite de 0,02 est une hypothèse illustrée et modifiable. Les 20 options ne l’établissent pas.

## Passage ponctuel de Dupire avec un facteur spatial général

Pour une diffusion de gains satisfaisant l’équation de Dupire avec densité positive, $C(T,k)=\mathbb E[(M_T-k)^+]$ donne $\sigma_M^2(T,k)=2C_T/(k^2 C_{kk})$. La commande `pointwise-dupire` traite cette équation à $T_1$, $k=78$, pour des familles dont on connaît deux bornes uniformes de régularité. Elle utilise la région européenne conjointe du P3 et permet une dépendance générale du coefficient en temps et en état. [Notes de l’Imperial College, section 4.1](https://www.ma.imperial.ac.uk/~ajacquie/IC_AMDP/IC_AMDP_Docs/AMDP.pdf).

Si $|C_{TT}(\cdot,k)|\le L_t$ sur $[T_1,T_2]$ et $|C_{kkkk}(T_1,\cdot)|\le L_k$ sur $[k-h,k+h]$, avec $T$ en années ACT/365F et $h=4$ EUR, les différences finies $N,D$ de [METHOD.md](METHOD.md) vérifient
$$
|2C_T-N|\le L_t\Delta T,\qquad |k^2 C_{kk}-D|\le k^2 h^2 L_k/12 .
$$
Le premier reste résulte de la moyenne de $C_T$ dans le temps, le second de la formule de Taylor symétrique en strike. Posons ces erreurs $e_N,e_D$ et $d_{\min}=\inf_{\rm cert}D\ge264{,}16416380$ EUR, une borne inférieure certifiée. Pour chaque signe $\epsilon$ la preuve duale fournit $u\ge\sup(\epsilon N-\alpha D)$. Si $d_{\min}>e_D$, le code en déduit
$$
\epsilon\sigma_M^2(T_1,k)\le\alpha+
\frac{\max(0,u+e_N+|\alpha|e_D)}{d_{\min}-e_D}.
$$
Le calcul indique explicitement si la densité positive reste indécidable. Les constantes doivent être justifiées sur la famille de modèles retenue. La commande suivante illustre la syntaxe avec des hypothèses numériques de l’utilisateur.

~~~powershell
python .\p3\p3_eurex.py pointwise-dupire --time-curvature 40 --strike-fourth 0.003
~~~

Avec une surface européenne connue sur un voisinage et une densité positive, les dérivées de Dupire déterminent la valeur ponctuelle. Pour une suite de panels, l’identification par cet encadrement demande que les incertitudes conjointes sur les dérivées s’annulent, que les restes de discrétisation tendent vers zéro et que le dénominateur garde une borne strictement positive. Un maillage de solveur plus fin sur les mêmes 20 cotations réduit le budget numérique, tout en laissant subsister les deux diffusions explicites de l’exemple.

Les observations et leurs conditions de diffusion sont documentées dans [RIGHTS_SOURCES.md](RIGHTS_SOURCES.md). Les empreintes du panel et de la preuve P3 lient les deux certificats.

