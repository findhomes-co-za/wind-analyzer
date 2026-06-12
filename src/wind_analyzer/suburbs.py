"""Suburbs of interest and terrain landmarks (approximate centroids)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .diagnostics import SurfaceFields
from .terrain import TerrainGrid


@dataclass
class Suburb:
    name: str
    lat: float
    lon: float
    group: str
    radius_m: float = 550.0


SUBURBS = [
    # --- City Bowl ---
    Suburb("CBD", -33.9249, 18.4232, "City Bowl", 700),
    Suburb("Foreshore", -33.9180, 18.4307, "City Bowl", 600),
    Suburb("De Waterkant", -33.9165, 18.4178, "City Bowl", 400),
    Suburb("Bo-Kaap", -33.9203, 18.4112, "City Bowl", 450),
    Suburb("Gardens", -33.9347, 18.4117, "City Bowl"),
    Suburb("Tamboerskloof", -33.9332, 18.4006, "City Bowl"),
    Suburb("Higgovale", -33.9395, 18.4030, "City Bowl", 400),
    Suburb("Oranjezicht", -33.9419, 18.4119, "City Bowl"),
    Suburb("Vredehoek", -33.9405, 18.4225, "City Bowl"),
    Suburb("Devil's Peak Estate", -33.9385, 18.4321, "City Bowl", 400),
    Suburb("District Six", -33.9303, 18.4322, "City Bowl"),
    Suburb("Walmer Estate", -33.9320, 18.4400, "City Bowl", 400),
    Suburb("Woodstock", -33.9266, 18.4459, "City Bowl", 700),
    Suburb("Salt River", -33.9272, 18.4626, "City Bowl", 600),
    # --- Atlantic Seaboard ---
    Suburb("V&A Waterfront", -33.9067, 18.4201, "Atlantic Seaboard", 600),
    Suburb("Mouille Point", -33.8999, 18.4055, "Atlantic Seaboard", 450),
    Suburb("Green Point", -33.9056, 18.4101, "Atlantic Seaboard"),
    Suburb("Three Anchor Bay", -33.9097, 18.3990, "Atlantic Seaboard", 400),
    Suburb("Sea Point", -33.9170, 18.3870, "Atlantic Seaboard", 700),
    Suburb("Fresnaye", -33.9258, 18.3823, "Atlantic Seaboard"),
    Suburb("Bantry Bay", -33.9282, 18.3759, "Atlantic Seaboard", 400),
    Suburb("Clifton", -33.9365, 18.3776, "Atlantic Seaboard", 450),
    Suburb("Camps Bay", -33.9508, 18.3776, "Atlantic Seaboard", 700),
    Suburb("Bakoven", -33.9609, 18.3741, "Atlantic Seaboard", 400),
    Suburb("Llandudno", -34.0089, 18.3417, "Atlantic Seaboard", 500),
    Suburb("Hout Bay", -34.0479, 18.3565, "Atlantic Seaboard", 900),
    # --- Southern Suburbs ---
    Suburb("Observatory", -33.9377, 18.4719, "Southern Suburbs", 600),
    Suburb("Mowbray", -33.9450, 18.4775, "Southern Suburbs", 600),
    Suburb("Rondebosch", -33.9610, 18.4730, "Southern Suburbs", 700),
    Suburb("Newlands", -33.9770, 18.4470, "Southern Suburbs", 700),
    Suburb("Claremont", -33.9810, 18.4650, "Southern Suburbs", 700),
    Suburb("Bishopscourt", -33.9870, 18.4320, "Southern Suburbs", 600),
    Suburb("Kenilworth", -33.9950, 18.4710, "Southern Suburbs", 700),
    Suburb("Wynberg", -34.0050, 18.4620, "Southern Suburbs", 700),
    Suburb("Constantia", -34.0260, 18.4210, "Southern Suburbs", 1200),
    Suburb("Plumstead", -34.0170, 18.4770, "Southern Suburbs", 700),
    Suburb("Bergvliet", -34.0440, 18.4600, "Southern Suburbs", 700),
    Suburb("Tokai", -34.0660, 18.4300, "Southern Suburbs", 800),
    Suburb("Retreat", -34.0600, 18.4780, "Southern Suburbs", 700),
    Suburb("Muizenberg", -34.1050, 18.4690, "Southern Suburbs", 800),
    # --- South Peninsula ---
    Suburb("Kalk Bay", -34.1280, 18.4490, "South Peninsula", 500),
    Suburb("Fish Hoek", -34.1370, 18.4260, "South Peninsula", 800),
    Suburb("Glencairn", -34.1600, 18.4320, "South Peninsula", 500),
    Suburb("Simon's Town", -34.1930, 18.4330, "South Peninsula", 800),
    Suburb("Noordhoek", -34.1030, 18.3650, "South Peninsula", 900),
    Suburb("Kommetjie", -34.1380, 18.3280, "South Peninsula", 600),
    Suburb("Ocean View", -34.1480, 18.3530, "South Peninsula", 600),
    Suburb("Scarborough", -34.1980, 18.3730, "South Peninsula", 500),
    Suburb("Cape Point", -34.3570, 18.4880, "South Peninsula", 800),
    # --- Cape Flats ---
    Suburb("Pinelands", -33.9300, 18.5130, "Cape Flats", 700),
    Suburb("Langa", -33.9440, 18.5300, "Cape Flats", 600),
    Suburb("Athlone", -33.9670, 18.5020, "Cape Flats", 800),
    Suburb("Manenberg", -33.9820, 18.5470, "Cape Flats", 600),
    Suburb("Gugulethu", -33.9800, 18.5820, "Cape Flats", 800),
    Suburb("Nyanga", -33.9910, 18.5770, "Cape Flats", 600),
    Suburb("Delft", -33.9700, 18.6450, "Cape Flats", 900),
    Suburb("Blue Downs", -33.9950, 18.6850, "Cape Flats", 800),
    Suburb("Eerste River", -34.0120, 18.7260, "Cape Flats", 800),
    Suburb("Mitchells Plain", -34.0500, 18.6180, "Cape Flats", 1500),
    Suburb("Khayelitsha", -34.0400, 18.6770, "Cape Flats", 1500),
    Suburb("Grassy Park", -34.0490, 18.5030, "Cape Flats", 700),
    Suburb("Strandfontein", -34.0800, 18.5580, "Cape Flats", 800),
    # --- Northern Suburbs ---
    Suburb("Milnerton", -33.8850, 18.4850, "Northern Suburbs", 700),
    Suburb("Table View", -33.8230, 18.4900, "Northern Suburbs", 900),
    Suburb("Bloubergstrand", -33.8000, 18.4600, "Northern Suburbs", 600),
    Suburb("Parklands", -33.8100, 18.5100, "Northern Suburbs", 800),
    Suburb("Century City", -33.8920, 18.5100, "Northern Suburbs", 700),
    Suburb("Bothasig", -33.8640, 18.5370, "Northern Suburbs", 600),
    Suburb("Edgemead", -33.8730, 18.5460, "Northern Suburbs", 600),
    Suburb("Plattekloof", -33.8730, 18.5850, "Northern Suburbs", 700),
    Suburb("Goodwood", -33.9060, 18.5460, "Northern Suburbs", 800),
    Suburb("Parow", -33.9000, 18.6000, "Northern Suburbs", 900),
    Suburb("Bellville", -33.9000, 18.6290, "Northern Suburbs", 1000),
    Suburb("Durbanville", -33.8300, 18.6500, "Northern Suburbs", 1100),
    Suburb("Brackenfell", -33.8750, 18.6940, "Northern Suburbs", 1000),
    Suburb("Kraaifontein", -33.8470, 18.7200, "Northern Suburbs", 1000),
    Suburb("Kuils River", -33.9200, 18.6800, "Northern Suburbs", 900),
    # --- Helderberg ---
    Suburb("Macassar", -34.0630, 18.7680, "Helderberg", 800),
    Suburb("Somerset West", -34.0790, 18.8430, "Helderberg", 1300),
    Suburb("Strand", -34.1070, 18.8270, "Helderberg", 1000),
    Suburb("Gordon's Bay", -34.1580, 18.8670, "Helderberg", 800),
    # --- Winelands ---
    Suburb("Stellenbosch", -33.9370, 18.8600, "Winelands", 1300),
]

LANDMARKS = [
    ("Table Mountain", -33.9628, 18.4035, 1085),
    ("Lion's Head", -33.9358, 18.3890, 669),
    ("Signal Hill", -33.9173, 18.3998, 350),
    ("Devil's Peak", -33.9590, 18.4395, 1000),
    ("Kloof Nek", -33.9460, 18.3950, 300),
    ("Constantia Nek", -34.0146, 18.4060, 280),
    ("Constantiaberg", -34.0570, 18.3850, 928),
    ("Chapman's Peak", -34.0800, 18.3540, 593),
    ("Karbonkelberg", -34.0440, 18.3270, 653),
    ("Muizenberg Peak", -34.0980, 18.4430, 506),
    ("Tygerberg", -33.8740, 18.5950, 455),
    ("Helderberg", -34.0430, 18.8720, 1138),
    ("Simonsberg", -33.8730, 18.9250, 1399),
    ("Stellenbosch Mtn", -33.9650, 18.8920, 1175),
    ("Sir Lowry's Pass", -34.1420, 18.9260, 450),
    ("Cape Point", -34.3565, 18.4970, 249),
]


def sample_suburbs(terrain: TerrainGrid, sf: SurfaceFields,
                   subset: list[Suburb] | None = None) -> list[dict]:
    """Disk-average the surface fields over suburbs and rank by speed."""
    jj, ii = np.mgrid[0:terrain.ny, 0:terrain.nx]
    rows = []
    for sub in (subset if subset is not None else SUBURBS):
        j0, i0 = terrain.lonlat_to_ij(sub.lon, sub.lat)
        r_cells = sub.radius_m / terrain.dx
        disk = (jj - j0) ** 2 + (ii - i0) ** 2 <= r_cells ** 2
        if not disk.any():
            continue
        rows.append({
            "suburb": sub.name,
            "group": sub.group,
            "elev_m": float(terrain.zs[disk].mean()),
            "speed10_mean": float(sf.speed10[disk].mean()),
            "speed10_p90": float(np.percentile(sf.speed10[disk], 90)),
            "gust_mean": float(sf.gust[disk].mean()),
            "speedup": float(sf.speedup[disk].mean()),
            "ti_mean": float(sf.ti[disk].mean()),
            "rotor_mean": float(sf.rotor[disk].mean()),
            "deflection_mean": float(sf.deflection[disk].mean()),
            "channel_share": float(sf.channel_mask[disk].mean()),
            "coanda_share": float(sf.coanda_mask[disk].mean()),
            "downwash_share": float(sf.downwash_mask[disk].mean()),
        })
    rows.sort(key=lambda r: r["speed10_mean"], reverse=True)
    return rows
