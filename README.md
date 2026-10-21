# Go1 Pilot

Sterowanie psem **Unitree Go1 (EDU)** z laptopa z Windowsem: z klawiatury, myszką albo głosem po polsku.

Aplikacja łączy się z wbudowanym w psa brokerem MQTT, tym samym, którego używa oficjalna aplikacja Unitree na telefon. Nie trzeba kompilować SDK. Rozpoznawanie mowy (Vosk) działa offline, bo w sieci Wi-Fi psa nie ma internetu.

## Uruchomienie

Kliknij dwukrotnie `start.bat`. Otworzy się okno **Go1 Pilot** (Chrome albo Edge w trybie aplikacji).

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

Mów samą komendę, na przykład „wstań”, a nie „piesku, czy możesz wstać”. Program porównuje dwa rozpoznania mowy. Dzięki temu zwykła rozmowa, na przykład „dzisiaj skoczymy do kina”, nie uruchamia skoku.

Pasek pod przyciskiem mikrofonu pokazuje, czy dźwięk dochodzi. Gdy mikrofon jest wyciszony w Windows, okno pokaże przycisk **Włącz mikrofon**. Możesz też wybrać inny mikrofon z listy, na przykład słuchawki.

## Bezpieczeństwo

- Pies staje, gdy puścisz klawisze, przełączysz się na inne okno, zamkniesz okno albo się rozłączysz.
- **Zwiotcz silniki** wyłącza napięcie w silnikach, więc pies opada na ziemię. Aplikacja pyta przed tym o potwierdzenie.
- Po zamknięciu okna program w tle sam się wyłącza po 2 minutach.

## Testy

```
.venv\Scripts\python.exe -m unittest -v
```
