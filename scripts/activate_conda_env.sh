#!/bin/bash

# Non-interactive WSL shells do not load .bashrc, so `conda` is often absent
# from PATH even when Miniconda/Miniforge is installed.
dhjr_activate_conda_env() {
    local conda_exe="${1:-conda}"
    local environment="${2:-}"
    local profile

    if [ "$conda_exe" = "micromamba" ]; then
        return 2
    fi

    if ! command -v "$conda_exe" >/dev/null 2>&1; then
        for profile in \
            /home/*/miniconda3/etc/profile.d/conda.sh \
            /home/*/miniforge3/etc/profile.d/conda.sh \
            /home/*/mambaforge/etc/profile.d/conda.sh; do
            if [ -f "$profile" ]; then
                # shellcheck disable=SC1090
                . "$profile"
                break
            fi
        done
    fi

    if ! command -v "$conda_exe" >/dev/null 2>&1; then
        return 127
    fi

    eval "$("$conda_exe" shell.bash hook)" || return 1
    conda activate "$environment"
}
