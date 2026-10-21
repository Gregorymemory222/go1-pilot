# Go1 Pilot

Proste okienko do sterowania psem **Unitree Go1 (EDU)** z laptopa z Windowsem.

Aplikacja łączy się z wbudowanym w psa brokerem MQTT, tym samym, którego używa oficjalna aplikacja Unitree na telefon. Nie trzeba kompilować SDK.

## Połączenie z psem

1. Włącz psa i poczekaj, aż wstanie (ok. 1 min).
2. **Wariant Wi-Fi (najprostszy):** połącz laptopa z siecią psa `Unitree_Go…` (hasło zwykle `00000000`).
   Adres w aplikacji: `192.168.12.1`.
3. **Wariant kabel Ethernet:** ustaw na karcie Ethernet laptopa stały adres IP `192.168.123.51`, maska `255.255.255.0`.
   Adres w aplikacji: `192.168.123.161`.
4. Zamknij aplikację Unitree na telefonie, żeby dwa piloty nie sterowały psem naraz.

## Uruchomienie

Kliknij dwukrotnie `start.bat`. Przy pierwszym uruchomieniu skrypt sam zainstaluje biblioteki.

## Sterowanie

| Klawisz | Ruch |
|---|---|
| W / S | przód / tył |
| A / D | bokiem w lewo / prawo |
| Q / E | obrót w lewo / prawo |
| R / F | głowa w górę / dół (w trybie „Stój (poza)”) |
| Spacja | zatrzymaj ruch |

Typowa kolejność: **Połącz → Wstań → Chód → WASD**.

Przyciski: Wstań, Połóż się, Podnieś po upadku, Stój (poza), Chód, Bieg, Wspinaczka, Taniec 1 i 2, Podaj łapę, kolor LED.

**ZWIOTCZ SILNIKI** wyłącza napięcie w silnikach, więc pies opada na ziemię. Używaj tego tylko w awaryjnej sytuacji albo gdy pies już leży.

Bezpieczeństwo: gdy puścisz klawisze, okno straci fokus albo się rozłączysz, aplikacja wysyła „stop”.

## Testy

```
.venv\Scripts\python.exe -m unittest -v
```
