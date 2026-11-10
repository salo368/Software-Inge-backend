import json


class _JsonSingletonStore:

    _instances = {}
    _filepath = ""

    def __new__(cls):
        if cls not in cls._instances:
            instance = super().__new__(cls)
            with open(cls._filepath, encoding="utf-8") as f:
                instance._data = json.load(f)
            cls._instances[cls] = instance
        return cls._instances[cls]

    @property
    def data(self) -> dict:
        return self._data


class _ColombianLocationsStore(_JsonSingletonStore):
    _filepath = "libs/data/locations_cities.json"


class _CountriesStore(_JsonSingletonStore):
    _filepath = "libs/data/locations_countries.json"


class ColombianLocations:
    @classmethod
    def _load_data(cls) -> dict:
        return _ColombianLocationsStore().data

    @classmethod
    def get_departments(cls) -> list[str]:
        return list(cls._load_data().keys())

    @classmethod
    def get_departments_map(cls) -> dict[str, dict[str, str]]:
        return {
            key: {"label": info.get("label", key)}
            for key, info in cls._load_data().items()
        }

    @classmethod
    def get_department(cls, department: str | None) -> dict | None:
        if not department:
            return {}
        return cls._load_data().get(department) or {}

    @classmethod
    def get_cities(cls, department: str) -> list[str]:
        cities = cls._load_data().get(department, {}).get("cities", {})
        return list(cities.keys())

    @classmethod
    def get_cities_map(cls, department: str) -> dict[str, dict[str, str]]:
        cities = cls._load_data().get(department, {}).get("cities", {})
        return {
            key: {
                "label": info.get("label", key),
                "dane_code": info.get("dane_code"),
            }
            for key, info in cities.items()
        }

    @classmethod
    def get_city(cls, department: str | None, city: str | None) -> dict | None:
        if not department or not city:
            return {}
        return cls._load_data().get(department, {}).get("cities", {}).get(city) or {}

    @classmethod
    def get_dane_code(cls, department: str, city: str) -> str | None:
        info = cls.get_city(department, city)
        return info.get("dane_code") if info else None



class Countries:
    @classmethod
    def _load_data(cls) -> dict:
        return _CountriesStore().data

    @classmethod
    def get_countries(cls) -> list[str]:
        return list(cls._load_data().keys())

    @classmethod
    def get_countries_map(cls) -> dict[str, dict[str, str]]:
        return {
            key: {
                "label": info.get("label", key),
                "abbr": info.get("abbr"),
            }
            for key, info in cls._load_data().items()
        }

    @classmethod
    def get_country(cls, country: str | None) -> dict | None:
        if not country:
            return {}
        return cls._load_data().get(country) or {}


class Location:

    COLOMBIA_KEY = "COLOMBIA"

    def __init__(self, country, department, city):

        self.country_label = None
        self.department_label = None
        self.city_label = None
        self.dane_code = None

        country_info = Countries.get_country(country)

        if country == self.COLOMBIA_KEY:
            department_info = ColombianLocations.get_department(department)
            city_info = ColombianLocations.get_city(department, city)

            if department_info and city_info:
                self.country_label = country_info.get("label")
                self.department_label = department_info.get("label")
                self.city_label = city_info.get("label")
                self.dane_code = city_info.get("dane_code")

        elif country_info:
            self.country_label = country_info.get("label")
            self.department_label = department
            self.city_label = city

    def full_name(self, include_country: bool = True, separator: str = ", ") -> str:

        parts = [self.city_label, self.department_label]
        if include_country:
            parts.append(self.country_label)
        return separator.join(filter(None, parts))


class IssuanceLocation(Location):

    def __init__(self, country, department, city):
        super().__init__(country, department, city)

        if self.city_label is not None:
            return

        if country != self.COLOMBIA_KEY:
            return

        department_info = ColombianLocations.get_department(department)
        if not department_info:
            return

        for parent_city_info in department_info.get("cities", {}).values():
            locality_info = (parent_city_info.get("localities") or {}).get(city)
            if not locality_info:
                continue

            self.country_label = Countries.get_country(country).get("label")
            self.department_label = department_info.get("label")
            self.city_label = locality_info.get("label")
            self.dane_code = parent_city_info.get("dane_code")
            return
