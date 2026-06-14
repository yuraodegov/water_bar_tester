"""
core/hc_config.py — IL / US parameter profiles.
Source: PRD D001628 Rev 20.0, Test Plan Section 4.
Temperatures in whole degrees C; durations in minutes unless noted.
"""


class Profile:
    def __init__(self, name, **kw):
        self.name = name
        self.__dict__.update(kw)


IL = Profile(
    "IL",
    BSP=96, BSPS=94, LBSP=93, HLSP=75, LLSP=70, TLLSP=50, TDRY=105,
    TTANK_TERMINATE=93, BTSP0=80, BTSP1=80, BTSP2=85, BTSP3=93,
    ISP=10, IHP=10, LBS=50, HBS=70, HDISP=70,
    SPMH1=50, SPMH2=20, SPMH3=10, B_OFFSET=3,
    IDLE_HEAT_TO=200, EH_TO=60, FT=10, HOT_FILL_TO=200, ERR159_TO=60,
    SHP=60, SHABBAT_TO=50, COLD_SP_SHABBAT=6, MANUAL_SHABBAT_MAX_H=80,
)

US = Profile(
    "US",
    BSP=95, BSPS=93, LBSP=92, HLSP=80, LLSP=75, TLLSP=60, TDRY=105,
    TTANK_TERMINATE=92, BTSP0=80, BTSP1=80, BTSP2=85, BTSP3=92,
    ISP=50, IHP=20, LBS=90, HBS=100, HDISP=100,
    SPMH1=50, SPMH2=20, SPMH3=10, B_OFFSET=3,
    IDLE_HEAT_TO=200, EH_TO=120, FT=10, HOT_FILL_TO=200, ERR159_TO=60,
    SHP=60, SHABBAT_TO=50, COLD_SP_SHABBAT=6, MANUAL_SHABBAT_MAX_H=80,
)

PROFILES = {"IL": IL, "US": US}
CRITICAL_ERROR_IDS = {18, 22, 55, 56}