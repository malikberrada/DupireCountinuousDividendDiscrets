# P2 · Certification des prix d’une grille de Dupire

## Énoncé et quantificateurs

On fixe des forwards et facteurs d’actualisation déterministes et un spot normalisé à 1. Pour chaque call européen on travaille en prix divisé par le produit du forward et du facteur d’actualisation, et en strike divisé par le forward. Le temps se mesure en années. La diffusion est une martingale continue positive de variation quadratique instantanée
\[
d\langle X\rangle_t=X_t^2 a(t,X_t)\,dt,\qquad 0<a_{\min}\le a\le a_{\max}<\infty .
\]
La variance bornée assure la propriété de vraie martingale sur un horizon fini. Sur une partition commune en temps et en spot, on fournit un plancher et un plafond rationnels **sur toute la cellule**, y compris les deux ailes jusqu’à 0 et à l’infini. Un changement de valeur sur une frontière de temps ou sur une droite verticale intérieure a une durée d’occupation nulle. Les modèles extrêmes emploient le plancher partout ou le plafond partout. Ils existent, par changement de temps d’un brownien sur chaque période. Un fichier à une seule cellule spatiale et un seul intervalle de temps représente la classe entière comprise entre deux constantes.

Pour un modèle de la classe, un contrat \(i\) et le prix **effectivement déclaré** \(p_i\), le calcul donne simultanément
\[
L_i\le C_i(a)\le U_i,\qquad
|C_i(a)-p_i|\le\eta_i=\max(p_i-L_i,U_i-p_i).
\]
Une fois les entrées fixées, il s’agit d’inégalités déterministes. Les bornes restent valables si les prix déclarés viennent d’un autre code. Pour attribuer la garantie au modèle calibré, celui-ci doit effectivement respecter les bandes. Un ensemble de valeurs nodales ne prouve pas cette propriété. La commande `from-plateau` construit les bandes à partir de la définition continue utilisée par P1. Sur chaque intervalle entre contrôles, le polynôme de transition \(10u^3-15u^4+6u^5\) a pour dérivée \(30u^2(1-u)^2\). Ses extrema sont donc aux bords. Le convertisseur traite les nœuds propres à chaque phase, le préfixe et les prolongements constants.

## 1. Réduire la famille à deux prix extrêmes

On commence sur un intervalle absorbant \([l,r]\). Sur une période, les coefficients extrêmes dépendent seulement du spot. Dans la représentation par changement de temps d’un brownien en échelle naturelle, le temps physique accumulé avant une sortie est l’intégrale en temps brownien de \(1/(aX^2)\). Sur la même trajectoire brownienne, les horloges physiques sont encadrées par celles des coefficients extrêmes. Leurs inverses sont donc ordonnés. L’arrêt optionnel d’un payoff convexe appliqué au brownien arrêté encadre sa valeur espérée à toute échéance. Cette comparaison s’applique aussi à une variance intérieure qui varie avec le temps dans la période.

Pour composer les périodes, les semi-groupes des extrêmes préservent la convexité. En effet, pour un payoff convexe \(f\), \(P_t f\) augmente avec la durée par Jensen conditionnelle. Pour \(y<x<z\), on arrête à la première sortie de \([y,z]\) ou à l’échéance. À la sortie, la valeur résiduelle est inférieure à la corde de \(P_t f\) entre \(y,z\). Avant la sortie, le payoff terminal est aussi sous la corde. L’espérance de la corde vaut sa valeur en \(x\), car le sous-jacent arrêté est une martingale. La récurrence à rebours donne l’ordre pour toutes les périodes. En envoyant les bords vers 0 et l’infini avec le contrôle de la section 2, on obtient l’ordre sur l’espace entier. Pour la classe rectangulaire déclarée, les deux extrêmes sont eux-mêmes admissibles. Des contraintes supplémentaires sur les paramètres peuvent exclure ces témoins.

Les calculs se font sur le put borné \((K-X)^+\). La parité ajoute exactement \(1-K\) au prix en spot initial 1, y compris pour la martingale arrêtée.

## 2. Sortie du domaine et comparaison analytique

À la première sortie, la différence entre continuer et arrêter est positive et au plus la valeur temps du call Black au bord, avec le plafond déterministe de variance intégrée restante. Cela découle de la comparaison convexe avec la volatilité déterministe maximale. Pour un cap intégré \(V\), on peut toujours majorer cette valeur temps en \(s\) par
\[
\min\big(s,K,s^2e^V/(4K),K^2e^V/(4s)\big).
\]
Ces estimations utilisent les seconds moments de \(X\) et l’inverse de \(X\). Elles suffisent à faire tendre le budget de troncature vers zéro.

Le calcul resserre ce budget par des probabilités de première atteinte. Pour \(r>1\), Doob appliqué à \(X^p\) donne \(r^{-p}\exp(p(p-1)V/2)\). Pour \(l<1\), \(X^{-p}\) donne \(l^p\exp(p(p+1)V/2)\). On prend le minimum de 1 et de plusieurs majorants rationnels certifiés avec \(p\ge1\). Quatre fractions du plafond déterministe de variance découpent le temps. Si \(b_j\) majore la valeur temps après un premier contact dans la tranche \(j\) et \(H_j\) majore la probabilité d’un contact avant sa fin, la sommation par parties donne \(\sum_j(b_j-b_{j+1})H_j\), avec \(b_5=0\) et \(b_j\) décroissants. Les coûts des deux bords s’additionnent. Le maximum brut des valeurs temps aux bords fournit un second majorant. Les ailes 0 et infinie ne contribuent pas.

Le même raisonnement donne un contrôle analytique indépendant sur chaque bande de spot contenant 1. Jusqu’à la sortie on encadre le modèle par deux volatilités déterministes égales aux extrema de la bande de spot à chaque date. Au prix Black inférieur on soustrait le budget de sortie de la référence inférieure. Au prix Black supérieur on ajoute le budget du modèle examiné. On intersecte les résultats de plusieurs bandes et de la grille. Les cotations ne servent jamais à calculer cet encadrement des prix.

## 3. Certificat a posteriori sur les valeurs réellement produites

Les dates de changement de coefficient, les frontières de spot, le strike et le spot initial sont des nœuds. Chaque modèle extrême est proposé par Euler implicite tridiagonal. À chaque date, les valeurs donnent une spline de Hermite cubique en spot, de classe C¹. La reconstruction est affine en temps à rebours entre deux dates et continue aux raccords de phases. La grille contient le coude du payoff, donc le payoff est affine par cellule. Le défaut initial est majoré par les coefficients de Bernstein du défaut de reconstruction.

Soient \(U^j\) les vecteurs proposés, \(L_h\) leur générateur, \(\delta_j\) le pas et
\[
d^j=U^j-U^{j-1}-\delta_j L_h U^j .
\]
On soustrait l’interpolant affine en spot de \(d^j\) du résidu intégré \(\delta_j(\partial_\tau S-a x^2 S_{xx}/2)\). Le reste est cubique en spot et affine en temps. Les coefficients de Bernstein aux deux bouts temporels majorent la norme sur la cellule en spot. La convexité de la norme permet d’intégrer la moyenne des deux majorants temporels. La somme donne `space_time_residual`. Le terme retiré est borné séparément par \(\sum_j\|d^j\|_\infty\), enregistré dans `linear_solve`.

La formule d’Itô appliquée à la reconstruction le long de la diffusion arrêtée donne une erreur de prix majorée par le défaut initial, le résidu intégré et le défaut algébrique. Les raccords C¹ en spot annulent les termes de temps local. Les valeurs aux bords sont le payoff arrêté. L’erreur de troncature s’ajoute du côté supérieur. La preuve relit les valeurs nodales enregistrées sous forme de rationnels, y compris lorsque SciPy a proposé ces valeurs.

## 4. Un raffinement démontré sur toute la famille

Le certificat possède un second majorant, indépendant de la qualité de la reconstruction de Hermite. Il évite de déduire la convergence d’une simple baisse observée du résidu.

Sur un triplet \(l_i<x_i<r_i\), \(P_i\) désigne l’interpolation linéaire des deux voisins en \(x_i\). La fonction chapeau de Green vaut \(G_i(y)=(r_i-x_i)(y-l_i)/(r_i-l_i)\) à gauche et \((x_i-l_i)(r_i-y)/(r_i-l_i)\) à droite. Posons \(D(y)=a(y)y^2/2\) et \(m_i=\int G_i/D\). La moyenne pondérée par \(G_i/D\), normalisée par \(m_i\), est notée \(M_i\). Pour la résolvante continue \(u=R_\delta f\), l’identité de Green intégrée deux fois donne
\[
P_i u-u(x_i)=\frac{m_i}{\delta}M_i(u-f).
\]
Pour un coefficient constant par cellule, \(u'\) est continu aux interfaces du modèle en échelle naturelle et \(u''=(u-f)/(\delta D)\) presque partout. Les multiplicateurs de Green sont positifs. On encadre \(m_i\) par deux intégrales rationnelles en remplaçant \(y^{-2}\) par ses extrema sur chaque demi-cellule. Le code prend leur milieu \(m_i^0\), calcule \(\rho=\max_i\sup|m_i/m_i^0-1|\) avec ces bornes et utilise \((L_h u)_i=(P_i u-u_i)/m_i^0\).

Une fonction 1-lipschitzienne le reste sous une résolvante arrêtée. Pour le voir, on couple deux diffusions parties de spots ordonnés indépendamment jusqu’à leur rencontre puis ensemble. Elles restent ordonnées et martingales. Leur distance moyenne vaut leur distance initiale. Le même argument s’applique aux semi-groupes et aux mélanges de durées. Les puts et toutes leurs valeurs intermédiaires appartiennent à \([0,K]\). Pour un pas spatial maximal \(h\), le défaut nodal d’une résolvante continue exacte dans le système implicite est donc inférieur à \(2h+K\rho\). Le terme \(2h\) majore l’oscillation de \(u-f\) et \(K\rho\) l’approximation de la masse. L’inverse de \(I-\delta L_h\) est une contraction en norme uniforme par le principe du maximum discret. On peut additionner ces défauts ainsi que les résidus algébriques vérifiés.

Sur une phase autonome de durée \(d\), composer des résolvantes revient à faire agir le semi-groupe pendant une somme \(G\) d’exponentielles indépendantes de moyennes \(\delta_j\). On a \(E G=d\) et \(\mathrm{Var}(G)=\sum_j\delta_j^2\). Pour un payoff 1-lipschitzien et un spot arrêté au plus à \(R\), l’isométrie d’Itô et Jensen donnent
\[
\|P_d f-E P_G f\|_\infty\le R\sqrt{a_{\max}}\,(\textstyle\sum_j\delta_j^2)^{1/4}.
\]
Les durées indépendantes interviennent seulement dans la preuve. Le calcul du majorant est déterministe. La composition de phases utilise la contraction des opérateurs de Markov. Au prix extrême arrêté, on ajoute le résidu algébrique et le minimum du majorant a posteriori de la section 3 et de la somme des majorants de la présente section.

**Règle.** Choisir d’abord un budget de domaine et éloigner les bords jusqu’à ce que la section 2 le respecte. Fixer alors ce domaine. Au niveau \(j\), doubler les pas par phase et quadrupler les cellules de spot par rapport au niveau précédent. Les temps sont gradués cubiquement à l’intérieur de chaque phase, donc \(\max \delta_j\le3d/n\). Les interfaces fixes appartiennent à toutes les grilles, \(h=O(4^{-j})\) et \(\rho\le(1+h/l)^2-1\) pour un bord gauche \(l>0\). Pour un nombre fixe de phases, le cumul spatial est \(O(2^{-j})\) et le majorant temporel \(O(2^{-j/4})\). Toutes les constantes sont uniformes pour les variances comprises dans les bandes. Le résidu de Hermite fournit souvent une borne beaucoup plus fine à un niveau accessible.

En mode `exact`, Thomas est résolu en rationnels puis arrondi sur un réseau dyadique de précision \(b_0+8j\). À domaine et interfaces fixés, la plus petite maille est asymptotiquement comparable à \(h\). Pour chaque arrondi, le défaut est au plus \(2^{-b}(1+2\delta\max_i 1/m_i^0)\). Le cumul est \(O(2^{-b}(n+h^{-2}))\) et tend donc vers zéro. Les racines carrées de la preuve ont aussi une précision dyadique croissante. En mode flottant, le défaut est toujours certifié a posteriori et peut finir par dominer. Le théorème de convergence constructive utilise le mode exact et un budget de travail suffisant. Pour toute précision sur les deux prix extrêmes, on réserve d’abord une fraction à la troncature puis on raffine. Sur un domaine fixé, le budget de troncature subsiste. Les intervalles successifs sont intersectés.

Cette convergence porte sur le calcul des **deux extrêmes**. À prix de grille donné \(p_i\), l’erreur physique maximale peut être positive même avec un calcul exact. Le rapport majore et minore cette erreur pour la classe rectangulaire. L’option `--target` compare la garantie totale au prix fourni avec le seuil demandé. Le plafond de travail et le nombre de niveaux peuvent laisser la cible ouverte.

## 5. Contre-exemple avec des observations nodales seules

Sur chaque intervalle d’une grille temporelle uniforme, posons \(u\in[0,1]\). Deux variances déterministes peuvent valoir respectivement \(a_0\) et \(a_0+16(a_1-a_0)u^2(1-u)^2\). Elles coïncident à tous les nœuds et sont C¹ au raccord. Les variances intégrées valent pourtant \(Ta_0\) et \(T(a_0+8(a_1-a_0)/15)\). La différence de prix Black à la monnaie est strictement positive pour \(a_1>a_0\), indépendamment du nombre de nœuds. La seconde fonction peut changer à chaque raffinement, ce qui est exactement le quantificateur d’une borne uniforme sur la classe. Pour un unique prix rapporté, au moins un de ces modèles subit une erreur d’au moins la moitié de cet écart. Cela justifie les hypothèses entre nœuds.

## 6. Optimisation, bid–ask et transfert à P1

Écrivons \(J(a)=\max_i d(C_i(a),[b_i,s_i])\). Une borne inférieure de l’infimum global est \(\max_i(0,b_i-U_i,L_i-s_i)\). Pour chacune des deux diffusions extrêmes **communes à tous les contrats**, les encadrements de ses prix donnent un majorant de \(J\). Le meilleur des deux majore l’infimum, et leur écart au minorant certifie la précision de l’optimisation minimax sur toute la classe déclarée. Deux modèles distincts peuvent réaliser le minimum par strike sans reproduire conjointement les prix. Cette construction du majorant conserve le même modèle pour tous les strikes. Pour une sous-famille plus restrictive, les témoins du majorant doivent appartenir à cette sous-famille.

La commande `p1-window` restreint chaque observation continue à \([b_i,s_i]\cap[L_i,U_i]\) puis appelle la routine P1 existante \(\texttt{continuous.outer_bounds}\) avec ces observations. En cas d’intersection vide, le contrat donne un motif d’exclusion. Pour un dénominateur positif, la moyenne pondérée par gamma appartient également aux extrema du coefficient sur le support du noyau. Le résultat conserve le certificat brut du numérateur et du dénominateur. Avec Dupire Identify 0.5.1, il recalcule aussi le minorant brownien du dénominateur par la fonction existante `denominator.brownian_floor`, vérifie sa preuve et prend le meilleur des deux minorants. Un minorant positif permet de majorer également le quotient par le majorant du numérateur divisé par ce minorant. Le statut des moments faibles seuls reste enregistré. Une hypothèse de variance plus restrictive dans P2 restreint d’autant la portée de P1. Une attestation existante du modèle continu conserve son interprétation d’origine.

La commande distincte `p1` traite l’objectif **affine** \(c^Tw\) sur des poids représentant des mélanges des familles vérifiées. Avec \(w\ge0\), \(\sum w_j=1\), les contraintes nécessaires de marché sont \(\sum_j L_{ij}w_j\le s_i\) et \(-\sum_j U_{ij}w_j\le-b_i\). Écrivons-les \(Aw\le b\). Pour tout multiplicateur rationnel \(y\ge0\), la borne inférieure certifiée vaut \(\min_j[c_j+(A^Ty)_j]-b^Ty\). Appliquer le même calcul à \(-c\) donne la borne supérieure. Une solution primale vérifiée dans le LP fournit l’écart d’optimisation de ce LP. Si aucune solution primale rationnelle n’est validée, le champ d’écart vaut `null` et les bornes duales restent valides. La faisabilité du LP extérieur ne démontre pas à elle seule l’existence d’une diffusion calibrée. Les poids représentent uniquement les modèles ou la relaxation de mélanges spécifiés. L’objectif gamma de P1 se traite avec `p1-window`.

## Références

Svante Janson et Johan Tysk, *Volatility time and properties of option prices*, Annals of Applied Probability 13 (2003), 890–913. Comparaison des prix convexes et changement de temps. [Article](https://www.ma.imperial.ac.uk/~ajacquie/IC_AMDP/IC_AMDP_Docs/Literature/Projects/JanssonTysk.pdf)

Antoine Conze et Pierre Henry-Labordère, *Bass construction with multi-marginals*, Risk. Les auteurs étudient la limite du modèle Bass-LV lorsque la grille des échéances se densifie. Ici le certificat évalue des prix à résolution finie et contrôle les erreurs d’un calcul effectivement produit. [Article](https://www.risk.net/media/download/1079736/download)
