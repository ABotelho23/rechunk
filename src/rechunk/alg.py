import logging

import numpy as np

from .fedora import get_packages
from .model import Package
from .utils import get_files, get_update_matrix, tqdm

logger = logging.getLogger(__name__)


def prefill_layers(
    packages: list[Package],
    upd_matrix: np.ndarray,
    max_layers: int,
    fill_size: int,
):
    layers = []

    # Use a dict because it maintains order
    # Important for reproducibility
    todo = dict.fromkeys(packages)
    n_segments = upd_matrix.shape[1]

    pbar = tqdm(total=max_layers, desc="Initial layer fill")
    layers = []
    curr = []
    l_upd = np.zeros(n_segments, dtype=np.bool)
    l_size = 0
    while todo:
        # We will fill layers in two steps:
        # If the layer is emptly, we will insert the largest package
        # in todo.
        # Afterwards, we will insert the package that will cause the
        # minimal bandwidth increase.
        #
        # There will be packages left over in the end, which will be handled
        # differently.

        if not curr:
            p = max(todo, key=lambda p: p.size)
            todo.pop(p)
            curr.append(p)
            l_upd |= upd_matrix[p.index]
            l_size += p.size
        elif l_size > fill_size:
            layers.append(curr)
            logger.info(
                f"Layer {len(layers):2d}: {l_size / 1e9:.3f} GB with {len(curr):3d} packages."
            )
            if len(layers) >= max_layers:
                break
            curr = []
            l_upd = np.zeros(n_segments, dtype=np.bool)
            l_size = 0
            pbar.update(1)
        else:
            # Calculate the bandwidth increase for each package
            # and select the one with the smallest increase
            b_upd = None
            b_pkg = None
            b_size = 0
            b_bw = 1e24
            for p in todo:
                upd = l_upd | upd_matrix[p.index]
                new_size = l_size + p.size
                bw = np.sum(upd) * new_size
                if bw < b_bw:
                    b_bw = bw
                    b_upd = upd
                    b_pkg = p
                    b_size = new_size

            assert (
                b_pkg is not None and b_upd is not None
            ), "No package selected. How did we get here?"

            todo.pop(b_pkg)
            curr.append(b_pkg)
            l_upd = b_upd
            l_size = b_size

    pbar.update(1)
    pbar.close()
    logger.info(
        f"Leftover packages: {len(todo)}/{len(packages)} with a size of {sum([p.size for p in todo]) / 1e9:.3f} GB."
    )
    return todo, layers


def fill_layers(
    todo: dict[Package, None],
    layers: list[list[Package]],
    upd_matrix: np.ndarray,
    max_layer_size: int,
):
    # Fill the layers with the leftover packages
    # We will fill the layers in the same way as before
    # but we will not create new layers.
    # We will insert the package that will cause the
    # minimal bandwidth increase.

    # Make a copy as we will muate
    todo = dict(todo)
    layers = [l.copy() for l in layers]
    pbar = tqdm(total=len(todo), desc="Final layer fill")
    n_segments = upd_matrix.shape[1]

    layer_size = [sum([p.size for p in l]) for l in layers]
    layer_upd = [np.zeros(n_segments, dtype=np.bool) for _ in range(len(layers))]
    for l in layers:
        for p in l:
            layer_upd[layers.index(l)] |= upd_matrix[p.index]
    layer_bw = [float(np.sum(layer_upd[i]) * layer_size[i]) for i in range(len(layers))]

    while todo:
        # There are still some leftover packages.
        # Since we did a heuristic to prefill the layers
        # we left out some space.
        #
        # Now we go back and do a computationally expensive step
        # and insert the packages in the layers that will cause
        # the least bandwidth increase.
        b_layer = None
        b_pkg = None
        b_upd = None
        b_bw = 1e24
        b_bw_total = 0
        for i in range(len(layers)):
            l_size = layer_size[i]
            if l_size > max_layer_size:
                continue
            for p in todo:
                upd = layer_upd[i] | upd_matrix[p.index]
                new_size = l_size + p.size
                bw_total = np.sum(upd) * new_size
                bw = bw_total - layer_bw[i]
                if bw < b_bw:
                    b_bw = bw
                    b_layer = i
                    b_pkg = p
                    b_upd = upd
                    b_bw_total = bw_total

        assert (
            b_layer is not None and b_pkg is not None and b_upd is not None
        ), "No package selected. How did we get here?"

        layers[b_layer].append(b_pkg)
        layer_upd[b_layer] = b_upd
        layer_size[b_layer] += b_pkg.size
        layer_bw[b_layer] = float(b_bw_total)
        todo.pop(b_pkg)
        pbar.update(1)

    pbar.close()
    return layers


def print_results(
    prefill_layers: list[list[Package]],
    layers: list[list[Package]],
    upd_matrix: np.ndarray,
):
    COMPRESSION_RATIO = 12 / 4.6  # This is for bazzite

    n_segments = upd_matrix.shape[1]

    # Update matrix for each layer
    layer_upd = [np.zeros(n_segments, dtype=np.bool) for _ in range(len(layers))]
    for l in layers:
        for p in l:
            layer_upd[layers.index(l)] |= upd_matrix[p.index]

    # Bandwidth calc
    total_bw = 0
    for i, l in enumerate(layers):
        total_bw += np.sum(layer_upd[i]) * sum([p.size for p in l])

    # Detailed package breakdown and frequency analysis
    logger.info(f"Packages in layers (sorted by frequency):")
    for i, l in sorted(
        enumerate(layers), key=lambda x: -float(np.sum(layer_upd[x[0]]))
    ):
        logger.info(
            f"{i+1:3d}: (pkg: {len(l):3d}, freq: {np.sum(layer_upd[i]):3d}, mb: {sum([p.size for p in l]) / 1e6 / COMPRESSION_RATIO:3.0f})",  #:\n{str([p.nevra for p in l])}",
        )

    # # Condensed results
    # log = f"Final layer fill:\n"
    # for i, (l, pl) in enumerate(zip(layers, prefill_layers)):
    #     log += f"Layer {i+1:2d}: {sum([p.size for p in l]) / 1e6:3.0f} MB "
    #     log += f"(compr. {sum([p.size for p in l]) / 1e6 / COMPRESSION_RATIO:3.0f}) with {len(l):3d}"
    #     if len(pl) != len(l):
    #         log += f" packages (prev {sum([p.size for p in pl]) / 1e6:3.0f} MB with {len(pl):3d}).\n"
    #     else:
    #         log += " packages.\n"
    # logger.info(log)

    logger.info(
        f"Total per update (uncompressed): {total_bw / (n_segments * 1e9):.3f} GB.\n"
        + f"Total per update (compressed): {total_bw / (n_segments * 1e9) / COMPRESSION_RATIO:.3f} GB.\n"
        + f"Layers changed per update: {np.sum([np.sum(u) for u in layer_upd]) / n_segments:.1f}."
    )


def main():
    # Hardcode for now
    dir = "./tree"
    max_layers = 40
    prefill_ratio = 0.6
    max_layer_ratio = 1.3


    # File analysis of treeusing root perms
    logger.info(f"Beginning analysis.")
    dir = "./tree"
    logger.info(f"Scanning directory '{dir}' for files.")
    files = get_files(dir)
    logger.info(f"Found {len(files)} files.")
    logger.info("Getting packages.")
    packages = get_packages(dir)
    logger.info(f"Found {len(packages)} packages.")

    # Size results
    total_size = sum([f.size for f in files])
    package_size = sum([p.size for p in packages])
    unpackage_size = total_size - package_size

    log = f"Size analysis:\n"
    log += f" - Packages: {package_size / 1e9:.3f} GB.\n"
    log += f" - Unpackaged: {unpackage_size / 1e9:.3f} GB.\n"
    log += f" - Total: {total_size / 1e9:.3f} GB."
    logger.info(log)

    # Calculate plan
    layer_size = total_size / max_layers
    prefill_size = int(layer_size * prefill_ratio)
    max_layer_size = int(layer_size * max_layer_ratio)
    logger.info(
        f"Rechunking into {max_layers} layers. Using:\n"
        + f" - Avg Layer size: {layer_size / 1e9:.3f} GB\n"
        + f" -   Prefill size: {prefill_size / 1e9:.3f} GB\n"
        + f" - Max layer size: {max_layer_size / 1e9:.3f} GB."
    )

    logger.info("Creating update matrix.")
    upd_matrix = get_update_matrix(packages)
    logger.info(f"Update matrix shape: {upd_matrix.shape}.")

    logger.info("Prefilling layers.")
    todo, prefill = prefill_layers(packages, upd_matrix, max_layers, prefill_size)

    logger.info("Filling layers.")
    layers = fill_layers(todo, prefill, upd_matrix, max_layer_size=max_layer_size)

    print_results(prefill, layers, upd_matrix)
