# Daily Stock Radar (DSR) — bindende werkspecificatie

Status: afgesproken werkwijze; nog niet volledig in software geïmplementeerd.
Doel: een betrouwbare, compacte dagelijkse beleggingsanalyse. De markt, kandidaten en beslissingen hebben prioriteit boven workflow-onderhoud.

## 1. Algemene uitvoeringsregels

1. Gebruik de laatst voltooide reguliere Amerikaanse handelssessie. Vermeld de datum van de koersgegevens.
2. Gebruik uitsluitend daadwerkelijk beschikbare en controleerbare gegevens. Verzin geen koers, score, pivot, sector, industry, volume, SW-score of short-beschikbaarheid.
3. Maak onderscheid tussen: ingelezen, technisch gecontroleerd, fundamenteel gecontroleerd en SW-gecontroleerd.
4. Ontbrekende of onbetrouwbare gegevens worden expliciet als ONBEKEND vermeld. Onbekend is nooit hetzelfde als akkoord.
5. Een ontbrekende controle mag de rest van het rapport niet stilzwijgend goedkeuren. Rapporteer de beperking en geef geen definitief positief actieadvies waarvoor de controle ontbreekt.
6. Wijzig bestaande bronbestanden, berekeningen, instellingen en uitvoerfrequenties niet zonder aantoonbare noodzaak en voorafgaande analyse.
7. Geen SMA200-filter of SMA200-weergave.

## 2. Vaste tickerbronnen

De DSR-universum wordt gevormd door deze zes bronnen, samengevoegd en ontdubbeld:

1. Sector Top Tickers — `tickers.txt`
2. FV Momentum Darvas — `finviz_tickers.csv` en `finviz_url.txt`; bestandsnamen/URL niet hernoemen
3. Blue Sky — `data/blue_sky_tickers.csv` en `blue_sky_url.txt`
4. VYUS holdings — `data/vyus_tickers.csv`
5. Simpel Monsters — `data/simpel_monsters_tickers.csv`
6. Follow Thrue — `data/follow_thrue_tickers.csv`

Geen TradingView-bron toevoegen. Blue Sky is de expliciet afgesproken zesde bron en wordt als afzonderlijke bron getoond; het is geen vervanging van FV Momentum Darvas.

Blue Sky wordt afzonderlijk ververst via `scripts/test_blue_sky.py` en daarna samen met de andere vijf bronnen opgenomen in de HA-merge via `data/dsr_ticker_sources.json`. De bronbestanden blijven gescheiden; de gecombineerde tickerlijst wordt ontdubbeld en behoudt per ticker alle bronvermeldingen.

Toon per ticker altijd de bron of alle bronnen waaruit de ticker afkomstig is. Gebruik in de presentatie de namen **FV Momentum Darvas** en **Blue Sky** voor de twee afzonderlijke Finviz-bronnen.

Toon per ticker altijd:
- Ticker
- Bron(nen)
- Sector
- Industry

Ontbrekende sector- of industrygegevens worden als ONBEKEND getoond, niet weggelaten of geraden.

Broncontrole vermeldt aantallen per bron, totaal ingelezen tickers, aantal unieke tickers na ontdubbelen, overlaps en eventuele bronfouten. Als één bron faalt, ga door met de overige bronnen en markeer de DSR als onvolledig.

## 3. Marktbeeld

Begin het rapport met een korte marktconclusie op basis van SPX en QQQ:
- trend en positie ten opzichte van SMA20 en SMA50;
- momentum en relevante steun-/weerstandsniveaus;
- relatieve sterkte/zwakte en algemene risk-on/risk-off-context.

Gebruik de meest recente voltooide sessie. Maak duidelijk wanneer een marktindicator niet is gecontroleerd. De marktcontext beïnvloedt de terughoudendheid en timing van adviezen, maar vervangt de individuele aandelentoets niet.

## 4. Technische basis voor Long en Short

- Technische beoordeling op een schaal van 3/5 tot en met 5/5 voor kandidaten die de selectie halen.
- SMA20 en SMA50 gebruiken; SMA200 niet gebruiken.
- RVOL-maatstaf is uitsluitend RVOL 5/21: gemiddelde dagomzet over de laatste 5 voltooide sessies gedeeld door het gemiddelde over de laatste 21 voltooide sessies.
- RVOL-duiding: <1 zwak; 1–<1,25 neutraal; 1,25–<1,50 positief; 1,50–2 sterk; >2 zeer sterk.
- De afzonderlijke indicator voor drie opeenvolgende dagen stijgend volume blijft apart staan. RSI verlaagt de technische score niet.
- Sector en industry worden per ticker vermeld.
- 52-weeks high en ATH zijn afzonderlijke referenties; gebruik split-aangepaste gegevens en vermeld ONBEKEND als betrouwbare verificatie ontbreekt.
- 52-weeks-high-balk: groen >100%, oranje 95–100%, rood <95%.
- ATH-balk: groen >=90%, oranje 85–<90%, rood <85%.

### Heikin-Ashi-signalen

Gebruik voor HA-condities uitsluitend Heikin-Ashi-OHLC; gebruik gewone slotkoers alleen voor de SMA20/SMA50-voorwaarde.

- HA Long: HA Close > HA Open, HA Low = HA Open en gewone slotkoers > SMA20 én SMA50.
- HA Short: HA Close < HA Open, HA High = HA Open en gewone slotkoers < SMA20 én SMA50.
- Toon in de HA-lijst uitsluitend signalen die aan alle voorwaarden voldoen.
- Sorteer UP- en DOWN-signalen afzonderlijk oplopend op afstand tot HA Low/HA High volgens de bestaande afgesproken afstandsmaatstaf. Toon afstand op één decimaal en signaalleeftijd.
- Maak HA UP/DOWN en HA Low=Open/HA High=Open expliciet zichtbaar. Verwar gewone candles niet met HA-candles.
- Een HA-signaal alleen is geen koop- of shortadvies.

## 5. Long-selectie — verplicht

### Voorselectie en kwaliteit

Momentum-breakoutbenadering, gebaseerd op Darvas, Minervini, O'Neil en IBD.

Algemene screeningsrichtlijnen:
- marktkapitalisatie minimaal USD 2 miljard;
- gemiddeld dagvolume minimaal 500.000 aandelen;
- koers boven SMA50;
- positieve operationele marge;
- ROE >10%;
- positieve omzetgroei op kwartaalbasis;
- debt/equity <1 waar betrouwbaar beschikbaar.
- Vermijd biotech-ontwikkelaars met klinisch/pijplijnrisico; leveranciers en dienstverleners aan biotech/healthcare zijn niet automatisch uitgesloten.
- NVDA blijft een expliciete uitzondering op de algemene terughoudendheid tegenover Mag7. Volg daarnaast MU, SK Hynix, Samsung/HBM en CGNX.

Ontbrekende fundamentele gegevens worden niet als geslaagd beschouwd. Maak zichtbaar welke criteria daadwerkelijk zijn gecontroleerd.

### Simply Wall St. (SW) — harde verplichte stap

Iedere Long-kandidaat moet vóór verdere Long-beoordeling een SW Financial Health-score krijgen of expliciet als onbekend worden aangemerkt.

- SW 4/6, 5/6 of 6/6: mag door naar de verdere Long-beoordeling.
- Geverifieerde SW-score lager dan 4/6: uitsluiten van verdere Long-behandeling; vermeld de score als uitsluitingsreden.
- SW onbekend/niet verifieerbaar: niet presenteren als goedgekeurde Long-kandidaat en geen positief koopadvies geven.
- VYUS: hergebruik een eerder vastgelegde, betrouwbare SW-beoordeling; voer niet dagelijks onnodig dezelfde controle opnieuw uit. Als er geen betrouwbare eerdere score is of een relevante aanleiding tot hercontrole bestaat, markeer de score als onbekend totdat deze is geverifieerd.
- Leg score, controledatum en bron vast zodat hergebruik controleerbaar is.
- SW is uitsluitend verplicht voor Long. Haal geen SW-scores op voor Short.

### Pivot en actieadvies

Bepaal vóór ieder Long-actieadvies het technische pivot-/weerstandsniveau van de actuele consolidatie. Verwar dit niet met de 52-weeks high of ATH.

Controleer:
- pivotniveau en onderbouwing;
- of de breakout al plaatsvond, met datum, officiële slotkoers en volume;
- of de koers nog binnen de gebruikelijke koopzone ligt: maximaal 5% boven het pivot;
- instap, stop, risico, koersdoel en technische haalbaarheid.

Mogelijke acties:
- KOPEN NU
- KOOP BIJ UITBRAAK BOVEN $X
- KOOP BIJ TERUGVAL NAAR $X
- WACHTEN OP BEVESTIGING
- VERMIJDEN — alleen bij concrete verslechtering of risico.

Voor de Long-watchlist geldt: instapkoers = actuele koers; stop-loss = laatste HA Low waarbij HA Low = HA Open; risk = afstand instap tot stop; minimaal reward/risk 2:1; koersdoel op 2R. Beoordeel eerst R/R en technische haalbaarheid van het koersdoel, daarna Risk %, daarna Entry Score.

## 6. Short-selectie — afzonderlijk en onafhankelijk

Gebruik dezelfde zes tickerbronnen, maar voer de technische Short-selectie onafhankelijk uit.

Technische kenmerken:
- koers onder SMA20 en SMA50;
- SMA20 < SMA50;
- lagere toppen en lagere bodems;
- negatieve relatieve sterkte tegenover QQQ, SPX en/of sector;
- steunbreuk en volumeconfirmatie;
- technische score 3/5 tot en met 5/5.

Geen fundamentele Long-filters en geen SW-score toepassen op Short.

Verplichte risicoanalyse vóór een Short-actieadvies:
- short interest en days-to-cover;
- squeeze-risico en scherpe rally's;
- nieuws, earnings en andere katalysatoren;
- liquiditeit en gap-risico;
- borrow availability en borrow fee uitsluitend indien betrouwbaar beschikbaar.

Noem een aandeel nooit shortbaar zonder geverifieerde beschikbaarheid/locate. Benoem het onbeperkte verliesrisico van shortposities.

Mogelijke acties:
- SHORTEN NU
- SHORTEN BIJ NEERWAARTSE DOORBRAAK ONDER $X
- SHORTEN BIJ HERSTEL NAAR WEERSTAND ROND $X
- WACHTEN
- VERMIJDEN ALS SHORT — alleen bij concrete reden.

Voor de Short-watchlist geldt dezelfde 2R-benadering gespiegeld voor een shortpositie: instap actuele koers; stop op de laatste HA High waarbij HA High = HA Open; risk = afstand instap tot stop; koersdoel op 2R. Beoordeel R/R en technische haalbaarheid, daarna Risk %, daarna Entry Score.

De Short-tabel toont een lege SW-kolom, uitsluitend om de kolommen uit te lijnen met de Long-tabel. Haal geen SW-scores op, bereken of beoordeel ze niet voor Short.

## 7. Nieuws en gebeurtenissen

Controleer voor serieuze kandidaten relevante recente informatie, waaronder earnings, outlook/guidance, contracten/orders, M&A, regelgeving, sectorontwikkelingen en analistenwijzigingen. Gebruik betrouwbare bronnen. Scheid bevestigde feiten van speculatie. Geen X als nieuwsbron.

## 8. Verplichte rapportage en volgorde

Rapporteer compact en conclusiegericht, in deze volgorde:

1. Datum van gegevens en marktconclusie (SPX/QQQ).
2. Brondekking en eventuele beperkingen.
3. Long-conclusie en Long-tabel.
4. Short-conclusie en Short-tabel.
5. HA-signalen die aan de afgesproken regels voldoen.
6. Concrete acties, instapniveaus, stops en doelen waar volledig geverifieerd.
7. Wat ontbreekt of nog niet gecontroleerd kon worden.

Iedere ticker in Long- en Short-overzichten bevat minimaal ticker, bron(nen), sector, industry, HA-status en technische score. Long bevat daarnaast SW-score en SW-status. Short toont een lege SW-kolom uitsluitend voor kolomuitlijning; er wordt geen SW-data voor Short opgehaald of beoordeeld. Toon alleen kandidaten die aan de relevante criteria voldoen; maak ontbrekende gegevens zichtbaar.

Gebruik de compacte, afgesproken statusconclusies:
- 🟢 KOOPWAARDIG
- 🟠 MONITOREN / WACHTEN
- 🔴 RISICOVOL / VERMIJDEN

Rood uitsluitend bij concrete verslechtering, risico of reden om te vermijden. Vermeld altijd afzonderlijke aantallen Long- en Short-kandidaten, ook wanneer er geen zijn.

## 9. Publicatiecontrole — geen stilzwijgende overslagen

Een rapport mag alleen **VOLLEDIGE DSR** heten als de verplichte onderdelen daadwerkelijk zijn uitgevoerd.

Controleer vóór publicatie:
- [ ] Zes bronnen verwerkt; bronfouten en dekking gemeld.
- [ ] Bron, sector en industry voor iedere ticker vermeld of expliciet ONBEKEND.
- [ ] Marktbeeld SPX/QQQ gecontroleerd.
- [ ] Long technische selectie uitgevoerd.
- [ ] SW voor iedere Long-kandidaat gecontroleerd of expliciet ONBEKEND; scores <4/6 uitgesloten.
- [ ] Long fundamentele criteria gecontroleerd.
- [ ] Pivot, breakout, instap, stop en 2R gecontroleerd voor ieder concreet Long-advies.
- [ ] Short technische selectie en afzonderlijke short-risicoanalyse uitgevoerd.
- [ ] Geen SW-controle voor Short.
- [ ] Gegevensdatum, beperkingen, aantallen en conclusies vermeld.

Als een onderdeel niet is uitgevoerd, label het rapport **GEDEELTELIJKE DSR** en benoem precies welke controles ontbreken. Presenteer nooit een gedeeltelijke selectie als volledig doorgelichte DSR.

## 10. Wijzigingsbeheer

Deze specificatie is de centrale referentie voor de DSR. Een wijziging in bronuniversum, selectiecriteria, formules, presentatie of frequentie vereist een expliciete afspraak. Bij technische aanpassingen:
1. inspecteer eerst bestaande code, instellingen, afhankelijkheden en geschiedenis;
2. wijzig alleen wat noodzakelijk is;
3. behoud werkende functionaliteit;
4. test met echte uitvoer en controleer de bestaande functionaliteit;
5. rapporteer wat wel en niet is getest.

De DSR blijft primair een dagelijks beleggingsinstrument. Technisch onderhoud krijgt alleen prioriteit wanneer een aantoonbare fout de marktuitkomst of betrouwbaarheid blokkeert.
