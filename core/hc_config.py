class Profile:
    def __init__(self, name, **kw):
        self.name = name
        self.__dict__.update(kw)


IL = Profile(
    "IL",
    BSP=96,
    BSPS=94,
    LBSP=93,
    HLSP=75,
    LLSP=70,
    TLLSP=50,
)
