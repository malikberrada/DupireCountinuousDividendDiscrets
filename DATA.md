# Data sources and reuse

This package is supplied for free access to the computations. The MIT license applies to the original software. The following sources retain their individual terms.

## TAIFEX and TWSE

The study uses European TXO options for the regular session of October 7, 2026 and the October 16 maturity, series `202610F3`. TAIFEX provides bid and ask quotes in index points. TWSE provides the TAIEX close of 49,806.37. Both responses were downloaded from the exchanges on November 21, 2026 UTC. The archive retains the response bytes under `p2/data/txo/sources/`. Source URLs and SHA-256 hashes are in the [acquisition record](p2/data/txo/sources/sources.json).

| Input | Official source | Transformation used in the calculation |
|---|---|---|
| `taifex.csv` | [TAIFEX daily options trading information, dataset 11320](https://data.gov.tw/en/datasets/11320) | Select the session and series, match calls and puts, and keep valid positive uncrossed bid–ask pairs. The canonical panel also binds rejected quote rows at the selected maturity. |
| `twse.json` | [TWSE weighted stock price index historical data, dataset 11755](https://data.gov.tw/en/datasets/11755) | Read the unique close for the requested Taipei date from the monthly response. |

These two data series are provided by the Taiwan Futures Exchange and Taiwan Stock Exchange through the Securities and Futures Bureau, Financial Supervisory Commission, Taiwan. They are used under the Open Government Data License, version 1.0. The research code performs the filtering, normalization and calculations. The sources do not endorse this work. [Open Government Data License v1.0](https://data.gov.tw/en/license)

A fresh monthly index response may include additional dates or different serialization. The verifier records both raw response hashes, checks the selected close and all dated option rows against the canonical panel digest, recomputes the parity region, and rechecks the five selected strikes. The archived byte hashes apply to the snapshots included here.

## Eurex, Xetra and Euronext

Deutsche Börse AG delayed MiFID II option and equity books supply the XEUR and XETB observations. Euronext N.V. delayed Paris derivatives trades supply an independent post-trade comparison. Data provided for non-commercial use and free distribution are subject to the respective providers' terms. Preserve the attribution and required notices when redistributing their data. Euronext's distribution terms address distribution for a fee or commercial benefit. The data must remain accessible under the provider terms when reused in another distribution. [Deutsche Börse delayed data](https://www.mds.deutsche-boerse.com/mds-en/real-time-data/Delayed-data) · [Euronext delayed trade terms, clauses 5–8](https://marketdata.euronext.com/data-reporting-service/trades-file) · [Required Euronext notice](p3/data/euronext/NOTICE.txt)

Euronext retains its original notice inside the dated ZIP. The P3 pipeline also writes the notice beside the generated trades table. The exact notices, source attribution, input transformations and links for Deutsche Börse, ESMA FIRDS, the ECB €STR series and DILA/TotalEnergies appear in [P3 sources and conditions](p3/RIGHTS_SOURCES.md). The [27-source manifest](p3/data/sources.json) and the [Euronext source record](p3/data/euronext/source.json) identify every European original. Original exchange books, the full ESMA archives and the issuer PDF can be reacquired into a local cache while available. The committed extracts and Euronext snapshot support the dated offline review.

## Software

The original project code and its accompanying notices retain the MIT license. The Windows certificate-store adapter uses the bundled truststore 0.10.5 code and its original MIT notice. Optional Python distributions retain their own licenses. [Project license](LICENSE) · [truststore license](p3/p3_vendor/truststore/LICENSE)
