from copy import deepcopy
from typing import Any
from .utils import PLATFORMS



def parse_config_(data: dict[str, Any]) -> dict[str, Any]:
    for k_section in data.keys():
        section: dict[str, Any] = data[k_section]

        # Separate default configs from platform-specific configs
        default_config = {}
        platform_config = {}
        to_remove = []
        for key, value in section.items():
            if key in PLATFORMS:
                platform_config[key] = value
            else:
                default_config[key] = value
                to_remove.append(key)
        for k in to_remove:
            del section[k]

        # Merge defaults with each platform-specific config
        for platform in PLATFORMS:
            # Create a new section for undefined platform
            if platform not in platform_config.keys():
                platform_config[platform] = {}

            # Merge default keys
            platform_default = deepcopy(default_config)
            to_remove = []
            for k, v in platform_config[platform].items():
                if not isinstance(v, dict):
                    platform_default.update({k: v})
                    to_remove.append(k)
            for k in to_remove:
                del platform_config[platform][k]

            # Append the consolidated default section
            platform_config[platform]['default'] = platform_default

        data[k_section] = platform_config

    return data



