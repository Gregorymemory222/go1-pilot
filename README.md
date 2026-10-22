# Go1 Pilot

Sterowanie psem **Unitree Go1 (EDU)** z laptopa z Windowsem: z klawiatury, myszką albo głosem po polsku.

Aplikacja łączy się z wbudowanym w psa brokerem MQTT, tym samym, którego używa oficjalna aplikacja Unitree na telefon. Nie trzeba kompilować SDK. Rozpoznawanie mowy (Vosk) działa offline, bo w sieci Wi-Fi psa nie ma internetu.

## Uruchomienie

Kliknij dwukrotnie skrót **Go1 Pilot** na pulpicie albo `start.bat`. Skrót z ikoną łapy tworzy `skrot-na-pulpit.bat`. Otworzy się okno **Go1 Pilot** (Chrome albo Edge w trybie aplikacji).

Przy **pierwszym** uruchomieniu potrzebny jest internet: skrypt instaluje biblioteki i pobiera polski model mowy (ok. 50 MB). Później wszystko działa bez internetu.

## Połączenie z psem

1. Włącz psa i poczekaj, aż wstanie (ok. 1 min).
2. **Wariant Wi-Fi (najprostszy):** połącz laptopa z siecią psa `Unitree_Go…` (hasło zwykle `00000000`).
   Adres w aplikacji: `192.168.12.1`.
3. **Wariant kabel Ethernet:** ustaw na karcie Ethernet laptopa stały adres IP `192.168.123.51`, maska `255.255.255.0`.
   Adres w aplikacji: `192.168.123.161`.
4. Zamknij aplikację Unitree na telefonie, żeby dwa piloty nie sterowały psem naraz.

Typowa kolejność: **Połącz → Wstań → jazda**. Gdy pies stoi, klawisze ruchu same włączą tryb „Chód”. Gdy leży, najpierw kliknij „Wstań”.

Po połączeniu w prawym górnym rogu widać baterię psa.

**Sztuczki** (taniec, łapa, skok z obrotem): jeśli pies nie reaguje, na jego pilocie wciśnij **L1 + L2 + Start** i spróbuj jeszcze raz. Według [notatek o Go1](https://github.com/MAVProxyUser/YushuTechUnitreeGo1) te ruchy działają tylko w tym trybie. Salto jest w Go1 zablokowane fabrycznie.

## Jazda (klawiatura albo kliknięcie i przytrzymanie)

| Klawisz | Ruch |
|---|---|
| W / S | przód / tył |
| A / D | bokiem w lewo / prawo |
| Q / E | obrót w lewo / prawo |
| R / F | głowa w górę / dół (w trybie „Poza”) |
| Spacja | zatrzymaj |

## Głos

Kliknij **Włącz słuchanie** i mów:

| Powiedz | Co się stanie |
|---|---|
| wstań · połóż się · podnieś się | postawa |
| chodź · biegaj · wspinaj się · poza | tryb ruchu |
| tańcz · taniec dwa · daj łapę · skocz · hop | sztuczki |
| do przodu · do tyłu · w lewo · w prawo | ruch przez 2 sekundy |
| bokiem w lewo · bokiem w prawo | krok w bok |
| obróć się · zawróć | obrót w miejscu |
| szybciej · wolniej | prędkość o 10% |
| stop · stój | zatrzymanie (działa od razu, jeszcze w trakcie mówienia) |

Po rozpoznaniu słychać dźwięk: wysoki podwójny = wykonane, niski = pominięte (nie wyglądało na komendę) albo brak połączenia z psem.

**W hałasie** (silniki psa, ludzie wokół) ustaw **Ustawienia → Głos → Mikrofon słucha: tylko gdy trzymasz V**. Wtedy program słucha tylko, gdy trzymasz klawisz **V** albo przycisk „Przytrzymaj i mów”.

Mów samą komendę, na przykład „wstań”, a nie „piesku, czy możesz wstać”. Program porównuje dwa rozpoznania mowy. Dzięki temu zwykła rozmowa, na przykład „dzisiaj skoczymy do kina”, nie uruchamia skoku.

Pasek pod przyciskiem mikrofonu pokazuje, czy dźwięk dochodzi. Gdy mikrofon jest wyciszony w Windows, okno pokaże przycisk **Włącz mikrofon**. Możesz też wybrać inny mikrofon z listy, na przykład słuchawki.

## Skróty klawiszowe

Pełna lista jest pod przyciskiem **Skróty** (klawisz **H**). Numery są też widoczne na przyciskach.

| Klawisz | Działanie |
|---|---|
| 1–7 | Wstań, Połóż się, Podnieś po upadku, Chód, Bieg, Wspinaczka, Poza |
| 8, 9, 0, J | Taniec 1, Taniec 2, Podaj łapę, Skok z obrotem |
| + / − | szybciej / wolniej |
| M | słuchanie wł./wył. |
| V | przytrzymaj i mów (tryb „naciśnij i mów”) |
| K | kamera wł./wył. |
| G | siatka wszystkich kamer |
| Z / N | zdjęcie / nagrywanie start-stop |
| P | kamera na pełnym ekranie (albo dwuklik na obrazie) – z nałożonym trybem, prędkością, baterią |

„Zwiotcz silniki” celowo nie ma skrótu.

## Kamera

Wybierz kamerę z listy nad klawiszami i kliknij **Włącz kamerę**.

Jak to działa: kamery Go1 są podłączone do komputerów Jetson w środku psa. Aplikacja loguje się przez SSH do Raspberry Pi psa (`pi` / `123`), stamtąd do komputera kamer (`unitree` / `123`), wysyła tam mały program `go1cam.py` i ogląda obraz przez ten tunel. Loginy pochodzą z [notatek o Go1](https://github.com/MAVProxyUser/YushuTechUnitreeGo1). Jeśli ktoś je zmienił, ustawisz je w **Ustawienia → Kamera**.

- Na czas podglądu zatrzymywane są fabryczne programy, które trzymają kamery: omijanie przeszkód i śledzenie ludzi. **Wracają po restarcie psa.**
- Nazwy kamer na liście („Głowa – kamera 1” itd.) są robocze. Przy pierwszym teście sprawdź, która jest z przodu, i ustaw ją jako domyślną. Aplikacja zapamiętuje ostatni wybór.
- Gdy obraz się tnie, zmień **Ustawienia → Kamera → Jakość obrazu** na niską.

**Siatka (G):** wszystkie 5 kamer naraz. Żeby nie zapchać Wi-Fi, w siatce kamery wysyłają 8 klatek na sekundę w niskiej jakości. Kliknięcie kafelka wraca do jednej kamery w pełnej jakości.

**Zdjęcie (Z)** i **nagrywanie (N):** pliki trafiają do `Obrazy\Go1 Pilot` i `Wideo\Go1 Pilot`. Szybko otworzysz je linkami „Zdjęcia” i „Nagrania” pod kamerą. Nagrania to pliki AVI (MJPEG), które otworzy VLC albo odtwarzacz Windows. Nagrywanie kończy się samo po 15 minutach.

## Ustawienia

Przycisk **Ustawienia** w prawym górnym rogu. Zapisują się w `settings.json`.

- **Połączenie:** adres psa i łączenie od razu po uruchomieniu.
- **Jazda i bezpieczeństwo:** prędkość maksymalna (limit suwaka), prędkość na start, automatyczny tryb „Chód”, pytanie przed zwiotczeniem silników.
- **Głos:** czas ruchu z komendy, czas obrotu, czułość rozpoznawania.
- **Kamera:** jakość obrazu i loginy do komputerów w psie.

**Dziennik** w prawej kolumnie pokazuje wszystko, co robi aplikacja: połączenie, komendy, rozpoznany głos i kroki kamery. Gdy coś nie działa, zrób zrzut dziennika.

## Polecenia tekstowe i kod w Pythonie (do nauki)

Pod głównymi panelami jest pole **Polecenia tekstowe**. Wpisz po polsku, na przykład:

> wstań, potem idź do przodu 2 sekundy, obróć się w lewo i połóż się

i naciśnij Enter. Po prawej pojawia się **kod w Pythonie**, który robi dokładnie to samo. Aplikacja wykonuje te same kroki, z których powstał kod, a wykonywana linijka jest podświetlona. Komendy głosowe też pokazują się jako kod.

Rozumie: wszystkie komendy głosowe, czas („2 sekundy”, „1,5 s”), tempo („szybko”, „wolno”, „bardzo wolno”), „czekaj 2 s”, „stop”. Kolejne kroki oddzielasz przecinkiem albo słowami „potem”, „następnie”, „i”.

Najwygodniej pracuje się w widoku **Programowanie** (przełącznik obok nazwy aplikacji): polecenie i kod zajmują wtedy cały ekran, a przycisk **A+** powiększa kod na rzutnik.

Parser niczego nie zgaduje. „biegnij na kolegę” to błąd („nie znam słów „na kolegę””), a nie samo „biegnij”. Dwie komendy bez przecinka („wstań skocz”) też są błędem, z podpowiedzią, jak to poprawić. Słowa grzecznościowe („proszę”, „teraz”, „trochę”) są pomijane.

### AI poprawia polecenia (Ustawienia → AI)

- **Wyłączone:** tylko polecenia, które zna parser.
- **Gdy polecenie nie jest zrozumiane:** „zrób kwadrat”, „podejdź i się przywitaj” albo polecenie z literówkami trafia do AI. AI przepisuje je na proste słowa, na przykład „do przodu 1 sekunda, w prawo 1 sekunda, …”.
- **Zawsze:** każde wpisane polecenie przechodzi przez AI.

AI nigdy nie steruje psem bezpośrednio. Zwraca tylko tekst, który przechodzi przez ten sam parser i te same limity bezpieczeństwa, a uczniowie widzą, co AI zmieniło (ramka nad krokami i komentarz w kodzie). Niebezpieczne polecenia AI odrzuca z wyjaśnieniem. Działa przez Claude Code (`claude -p`, Twoja subskrypcja, bez klucza API) i **potrzebuje internetu**. Wi-Fi psa go nie daje, więc podłącz psa kablem Ethernet (adres `192.168.123.161`), a internet daj przez Wi-Fi albo telefon. Komendy głosowe działają bez AI.

**Zapisz .py** zapisuje program w folderze `programy\`. Uczniowie mogą go uruchomić samodzielnie (`python program_….py`), korzystając z biblioteki `go1_client.py` z projektu. Przed uruchomieniem skryptu kliknij w aplikacji **Rozłącz**, żeby dwa programy nie sterowały psem naraz.

## Bezpieczeństwo: skąd pies wie, kiedy stanąć?

- **Pies sam nie wie, kiedy skończyć „idź do przodu”.** Idzie tak długo, jak długo dostaje polecenie ruchu. Dlatego aplikacja przy komendzie z głosu albo tekstu wysyła ruch tylko przez określony czas (domyślnie 2 s, najwyżej 8 s, w trybie lekcji 3 s), a potem sama wysyła „stop”. Tak samo działa wygenerowany kod: `set_stick(…)`, potem `time.sleep(…)`, potem `set_stick(0, 0, 0, 0)`.
- **Klawisze działają jak pedał gazu:** pies idzie tylko, dopóki trzymasz klawisz.
- **Zatrzymanie:** Spacja, przycisk „Zatrzymaj”, słowo „stop” (działa jeszcze w trakcie mówienia). Pies staje też, gdy okno zniknie albo zostanie zminimalizowane (po ok. 1 s) i przy rozłączeniu.
- **Czujniki psa:** Go1 ma fabryczne omijanie przeszkód (kamery i czujniki odległości). **Włączenie podglądu kamery w tej aplikacji je wyłącza** aż do restartu psa, co pokazuje żółty napis u góry okna. Sama aplikacja nie wykrywa ludzi ani przeszkód. Nie sprawdziliśmy jeszcze na psie, czy fabryczne omijanie działa przy sterowaniu z tej aplikacji, więc nie zakładaj, że działa.
- **Tryb lekcji** (Ustawienia → Jazda i bezpieczeństwo): najwyżej 30% prędkości, ruchy z poleceń najwyżej 3 s, bez biegu. Limit pilnuje serwer, więc obowiązuje też klawisze.
- **Na lekcji:** wolna strefa 2–3 m, uczniowie za linią, pilot psa w ręku prowadzącego (położenie psa pilotem: 2× L2 + A, potem L2 + B).

## Inne zabezpieczenia

- Pies staje, gdy puścisz klawisze, przełączysz się na inne okno, zamkniesz okno albo się rozłączysz.
- **Zwiotcz silniki** wyłącza napięcie w silnikach, więc pies opada na ziemię. Aplikacja pyta przed tym o potwierdzenie.
- Po zamknięciu okna program w tle sam się wyłącza po 2 minutach.

## Testy

```
.venv\Scripts\python.exe -m unittest -v
```
