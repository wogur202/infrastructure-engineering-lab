"""PyYAML compatibility for the literal '=' enums in upstream CRD schemas."""
import yaml


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("tag:yaml.org,2002:value", Loader.construct_scalar)


def documents(text):
    return [item for item in yaml.load_all(text, Loader=Loader) if item]
