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

Typowa kolejność: **Połącz → Wstań → Chód → jazda**.

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
| tańcz · taniec dwa · daj łapę | sztuczki |
| do przodu · do tyłu · w lewo · w prawo | ruch przez 2 sekundy |
| bokiem w lewo · bokiem w prawo | krok w bok |
| stop · stój | zatrzymanie |

Prędkość ruchu z głosu bierze się z suwaka. Gdy w pobliżu ktoś rozmawia, wyłącz słuchanie, bo pies może wziąć jakieś słowo za komendę.

## Bezpieczeństwo

- Pies staje, gdy puścisz klawisze, przełączysz się na inne okno, zamkniesz okno albo się rozłączysz.
- **Zwiotcz silniki** wyłącza napięcie w silnikach, więc pies opada na ziemię. Aplikacja pyta przed tym o potwierdzenie.
- Po zamknięciu okna program w tle sam się wyłącza po 2 minutach.

## Testy

```
.venv\Scripts\python.exe -m unittest -v
```
