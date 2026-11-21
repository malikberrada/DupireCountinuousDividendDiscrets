# Ensemble inverse commun et certificats

## Objet

Pour le contrat $i$, notons $A_i(m)$ son prix américain et $E_i(m)$ son prix européen au même strike, à la même échéance et selon la même convention de livraison. Les prix des équations suivantes sont en valeur actuelle. Les primes de marché sont multipliées par leur facteur de règlement. La projection exportée reconvertit les valeurs actuelles en primes cotées par action.

$$
\mathcal I=\{(E_i(m))_i\;|\;m\in\mathcal M,\ b_i\le A_i(m)\le a_i\ \text{pour tout }i\}.
$$

Le certificat fournit $I_{\rm int}\subseteq\mathcal I\subseteq I_{\rm ext}$. Il conserve une même loi, un même spot, une même courbe et un même calendrier de dividendes pour les 20 options. La recherche de témoins s’effectue sur des supports finis. La preuve de l’inclusion extérieure couvre aussi des distributions à support non borné.

## Numéraire, dividendes et livraison physique

Soit $P(d)=(1+r\,n(d)/360)^{-1}$, où $n(d)$ compte les jours calendaires depuis l’observation. Le taux plat est l’€STR observé converti en fraction annuelle. La prime est payable à T+1. Le spot observé et le strike à l’exercice sont des prix de livraison à T+2. Dans le calendrier utilisé, les jours d’exercice sont les jours de semaine, en excluant les 24, 25 et 31 décembre 2026 et le 1er janvier 2027. Le modèle utilise ces jours d’échange pour les décalages de règlement. Il compte les dates de détachement selon le calendrier de la ligne européenne, même lorsque la place de dérivés est fermée. Un autre calendrier de règlement peut être donné explicitement dans le panel.

Le modèle suppose un droit intégral au dividende pour une action achetée cum-dividende, y compris lorsqu’une compensation de livraison est nécessaire, un financement commun sans frais, aucune retenue fiscale et une courbe déterministe. Une dette ou une créance certaine de dividende est évaluée à sa date de paiement. Les 20 observations sont supposées représentatives d’une même coupe. On laisse le spot de modèle parcourir son bid–ask Xetra.

Écrivons $Q_d=\sum_{t_0<e_j\le d}P(p_j)D_j$, où $e_j,p_j,D_j$ sont le détachement, le paiement et le montant brut. $M$ est la martingale de gains totaux exprimés en euros de la date de valorisation. La valeur prépayée de l’action ex-dividendes vaut $M_d-Q_d$. On suppose cette valeur positive ou nulle et l’intégrabilité nécessaire à l’arrêt optionnel sur l’horizon. L’état initial $z=M_0$ est le spot de modèle multiplié par le facteur de règlement de l’action. Si $L(d)$ est le règlement d’un exercice effectué le jour $d$, son strike effectif est

$$
H_i(d)=Q_d+K_i P(L(d)).
$$

Le gain d’exercice en valeur actuelle est $g_c(x,h)=(x-h)^+$ pour un call et $g_p(x,h)=(h-x)^+$ pour un put. Les droits américains portent sur chaque jour d’exercice admissible. À l’intérieur d’une journée, le seuil reste constant car le jour de règlement est le même.

## Enveloppe extérieure

Pour tout arrêt admissible $\tau\le T_i$, la convexité de $g$ et le caractère martingale donnent

$$
g_i(M_\tau,H_i(T_i))\le {\mathbb E}[g_i(M_{T_i},H_i(T_i))\mid\mathcal F_\tau].
$$

Le déplacement du seuil donne donc $0\le A_i-E_i\le u_i$. Pour un call, $u_i=H_i(T_i)-\min_d H_i(d)$. Pour un put, $u_i=\max_d H_i(d)-H_i(T_i)$. Les extrêmes parcourent tous les jours d’exercice jusqu’à l’échéance. On impose $b_i-u_i\le E_i\le a_i$.

La fonction de call commune est $c_j(k)=\mathbb E[(M_{T_j}-k)^+]$. Pour tous les nœuds utilisés par les deux échéances, le programme impose $c_j(0)=z$, la positivité, la décroissance, des pentes comprises entre −1 et 0, la convexité et $c_1(k)\le c_2(k)$. Les puts ont pour valeur $c_j(k)+k-z$. Pour une option de seconde échéance, on impose également que sa borne d’offre couvre la valeur calculée à $T_1$ au meilleur seuil déterministe d’exercice entre les deux échéances. Jensen justifie cette contrainte, tout comme les contraintes d’exercice à partir de l’état initial. Toute loi compatible se projette donc dans `outer.json`. Certaines lois dans cette relaxation peuvent rester sans modèle compatible.

Pour $Ax\le b$, $0\le x\le U$, toute famille de multiplicateurs $\lambda\ge0$ donne, pour l’objectif affine $f(x)=c+d^\top x$,

$$
\sup f(x)\le c+\lambda^\top b+\sum_j U_j[d_j-(A^\top\lambda)_j]^+.
$$

Le vérificateur applique cette formule aux coefficients rationnels originaux. Le solveur flottant propose les multiplicateurs. Les résidus de stationnarité sont entièrement pris en compte. On applique la même formule à $-f$ pour la borne inférieure.

## Modèles réalisables et arrêt optimal

Chaque témoin donne $z$, la loi de $X=M_{T_1}$ et la loi de $Y=M_{T_2}$ conditionnellement à $X=x$. Les masses sont rationnelles, positives, de somme un. Les identités $\mathbb E X=z$ et $\mathbb E[Y\mid X=x]=x$ sont vérifiées exactement. Les supports restent au-dessus de la réserve de dividende. L’information nouvelle arrive dans la journée de chaque échéance, avant la fin de la fenêtre d’exercice.

Pour un seuil et une variété d’option donnés, posons $B_J(x)=\max_{d\in J} g(x,H(d))$. Le prix américain d’une option de seconde échéance est exactement

$$
\max\!\left\{
 B_{[0,T_1]}(z),\;
 \mathbb E\!\left[\max\!\left\{
 B_{[T_1,T_2]}(X),\ \mathbb E[g(Y,H(T_2))\mid X]
 \right\}\right]\right\}.
$$

Pour la première échéance, on compare la meilleure décision avant révélation à $\mathbb E[g(X,H(T_1))]$. Le prix européen est l’espérance du seul gain terminal. Ces maxima donnent l’enveloppe de Snell exacte du modèle. Le test indépendant parcourt également tous les jours d’exercice dans l’ordre inverse. L’optimisation des transitions utilise une décision admissible pour prouver la borne d’achat et des majorants de l’enveloppe de Snell pour la borne d’offre. La vérification finale recalcule le véritable optimum sur chaque loi.

Ces lois admettent une réalisation martingale **à trajectoires continues entre détachements**. Pendant une fenêtre intrajournalière de seuil constant, représenter la loi finie de l’état suivant par une fonction quantile $G(B_1)$ d’un brownien standard, en utilisant des seuils gaussiens donnant les masses de la loi. La martingale $\mathbb E[G(B_1)\mid B_s]$ part de la moyenne prescrite et atteint l’état discret à la fin de la fenêtre. Pour $s<1$, la convolution gaussienne est continue. À $s=1$, la convergence des trajectoires a lieu presque sûrement, puisque le brownien terminal évite les seuils. On recommence conditionnellement à la première branche avec un brownien indépendant. Entre fenêtres, le processus de gains est constant. Pendant une fenêtre, attendre sa fin puis exercer domine l’exercice anticipé au même seuil par Jensen conditionnelle. La réalisation continue conserve donc les prix américains et européens du témoin. L’action ex-dividende subit le saut de la créance détachée. Cette construction autorise des lois terminales atomiques et des dynamiques dégénérées ou dépendantes de la branche.

## Une famille intérieure entière

Le fichier de certificat contient les flux joints $p_xP_{xy}$ pour chaque témoin. Dans les trois premiers, le spot et les dates sont communs. Pour un vecteur $\theta$ du simplexe, combiner les flux joints avec les poids $\theta$, puis normaliser conditionnellement à chaque état de masse positive. Cette loi est martingale et son vecteur européen est la combinaison affine correspondante.

Dans la formule de Snell, la masse de chaque état multiplie un maximum. Le terme pondéré devient le maximum de deux fonctions linéaires des flux. Le maximum initial préserve la convexité. La valeur américaine de la loi mélangée est donc majorée par la moyenne des valeurs américaines. Elle satisfait la borne d’offre. Pour la borne d’achat, le code construit par contrat une politique commune explicite. Son espérance est linéaire dans les flux et vérifiée au-dessus du bid à chacun des trois sommets. Toute combinaison passe alors simultanément. Sur un autre jeu, si cette vérification échoue à un sommet, les lignes de `inner.lower_policy_rows` définissent la sous-partie certifiée du simplexe. Les autres témoins du fichier fournissent des points supplémentaires.

## Incertitude sur le dividende

À courbe, calendrier d’exercice et loi de gains identiques, toute variation des montants ou dates remplace $Q_d$ par $Q'_d$. Le gain d’exercice est 1-lipschitzien en $Q_d$. Ainsi

$$
|A'_i-A_i|\le\max_{d\le T_i,\ d\ \mathrm{exerçable}}|Q'_d-Q_d|,
\qquad |E'_i-E_i|\le|Q'_{T_i}-Q_{T_i}|.
$$

Le contrôle vaut pour le supremum sur les règles d’arrêt, même si la politique optimale change. `div-risk` calcule les extrêmes de la créance date par date pour toute la plage demandée et vérifie la réserve minimale sur les chemins du témoin. Les budgets sont reconvertis en unités de prime. Cette analyse de scénarios suppose que le calendrier testé est connu du modèle à la date d’observation. L’annonce future aléatoire d’un dividende demanderait une filtration supplémentaire.

## Propagation vers Dupire

Pour un strike fixe $k$ du processus de gains, le calcul encadre directement $2[c_2(k)-c_1(k)]$ sur la région conjointe. Dans un modèle martingale continu satisfaisant les conditions de Tanaka, cette quantité donne $\mathbb E[L^k_{T_2}(M)-L^k_{T_1}(M)]$, avec le temps local symétrique usuel. C’est un résultat en temps continu.

Pour la mesure discrète de variance, $h$ est l’espacement en strike et $\Delta T$ l’écart entre échéances en années ACT/365F. On forme

$$
N=2[c_2(k)-c_1(k)]/\Delta T,\qquad
D=\frac{k^2}{h^2}[c_1(k-h)-2c_1(k)+c_1(k+h)].
$$

Toutes les entrées proviennent du même vecteur auxiliaire de la région extérieure. Les preuves duales fournissent $D\ge d_{\min}>0$. Pour tout rationnel $q$, une borne supérieure vérifiée $u$ de $N-qD$ donne $N/D\le q+\max(0,u)/d_{\min}$. On procède de même pour $-N$. Si le certificat de positivité échoue, le quotient reçoit le statut `unresolved_denominator`. La différence seconde est l’espérance du poids triangulaire $(h-|M_{T_1}-k|)^+$. L’interprétation en volatilité locale ponctuelle d’une diffusion de Dupire nécessiterait des hypothèses de régularité, une famille de diffusions spécifiée et un contrôle du passage aux dérivées. Les bornes livrées portent sur le temps local et le quotient défini ci-dessus.

La désaméricanisation contrat par contrat et son risque méthodologique ont été étudiés par Burkovska, Gaß, Glau, Mahlstedt, Schoutens et Wohlmuth. L’apport documenté ici est la construction et la vérification d’un encadrement conjoint sur ce panel. [Calibration to American Options](https://arxiv.org/abs/1611.06181).
