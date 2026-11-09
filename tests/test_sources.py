import json

import pytest

from wheelgap.check import Status, check
from wheelgap.sources import SourceError, find_lockfile, load_inputs, parse_requirements
from wheelgap.targets import build_targets


def by_name(source):
    return {p.name: p for p in source.packages}


def test_uv_lock(fixtures):
    (src,) = load_inputs([str(fixtures / "uvproj")])
    pkgs = by_name(src)
    assert src.label == "uv.lock"
    assert pkgs["demo"].skip == "editable"
    assert pkgs["gitdep"].skip == "git"
    assert pkgs["fastlib"].files == [
        "fastlib-2.0.0-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
        "fastlib-2.0.0-cp313-cp313-macosx_11_0_arm64.whl",
        "fastlib-2.0.0-cp313-cp313-win_amd64.whl",
        "fastlib-2.0.0.tar.gz",
    ]
    assert pkgs["puresdist"].files == ["puresdist-1.0.tar.gz"]
    assert src.roots == [0]
    assert ("winonly", None, "sys_platform == 'win32'") in src.edges[0]
    assert ("devtool", None, None) in src.edges[0]


def test_uv_lock_dependency_group_names(tmp_path):
    (tmp_path / "uv.lock").write_text(
        'version = 1\n\n[manifest]\nrequirements = [{ name = "app" }]\n\n'
        '[manifest.dependency-groups]\ndev = [{ name = "pytest" }]\ndocs = [{ name = "sphinx" }]\n',
        encoding="utf-8",
    )
    (src,) = load_inputs([str(tmp_path)])
    assert [name for name, _, _ in src.root_edges] == ["pytest", "sphinx", "app"]
    assert src.root_groups == {0: "dev", 1: "docs"}  # the plain requirement has no group


def test_poetry_lock(fixtures):
    (src,) = load_inputs([str(fixtures / "poetryproj" / "poetry.lock")])
    pkgs = by_name(src)
    assert pkgs["fastlib"].files == ["fastlib-2.0.0-cp313-cp313-musllinux_1_2_aarch64.whl", "fastlib-2.0.0.tar.gz"]
    assert pkgs["backport"].markers == ['python_version < "3.13"']
    assert pkgs["localpkg"].skip == "directory"


@pytest.mark.parametrize("input_name", ["pdmproj", "pdmproj/pdm.lock"])
def test_pdm_lock(fixtures, input_name):
    (src,) = load_inputs([str(fixtures / input_name)])
    pkgs = by_name(src)
    assert src.label == "pdm.lock"
    assert pkgs["fastlib"].files == ["fastlib-2.0.0-cp313-cp313-musllinux_1_2_aarch64.whl", "fastlib-2.0.0.tar.gz"]
    assert pkgs["backport"].markers == ["python_version < '3.13'"]
    assert pkgs["localpkg"].skip == "path"
    assert all(p.origin == "pdm.lock" for p in src.packages)


def test_pylock(fixtures):
    (src,) = load_inputs([str(fixtures / "pylockproj")])
    pkgs = by_name(src)
    assert pkgs["fastlib"].files == ["fastlib-2.0.0-cp313-abi3-manylinux_2_28_aarch64.whl"]
    assert pkgs["macpkg"].files == ["macpkg-1.0.tar.gz"]
    assert pkgs["macpkg"].markers == ["sys_platform == 'darwin'"]


def test_requirements(fixtures):
    src = parse_requirements(fixtures / "reqproj" / "requirements.txt")
    pkgs = by_name(src)
    assert pkgs["fastlib"].version == "2.0.0"
    assert pkgs["fastlib"].files is None
    assert pkgs["unpinned"].version is None
    assert pkgs["winonly"].markers == ['sys_platform == "win32"']
    assert pkgs["purewheel"].version == "3.1"  # pulled in via -r
    assert pkgs["./localpkg"].skip == "editable"
    assert len(src.packages) == 5


@pytest.mark.parametrize("input_name", ["pipenvproj", "pipenvproj/Pipfile.lock"])
def test_pipfile_lock(fixtures, input_name):
    (src,) = load_inputs([str(fixtures / input_name)])
    pkgs = by_name(src)
    assert src.label == "Pipfile.lock"
    assert len(src.packages) == 7
    assert pkgs["fastlib"].version == "2.0.0"
    assert pkgs["fastlib"].markers is None
    assert pkgs["winonly"].version == "311"
    assert pkgs["winonly"].markers == ["sys_platform == 'win32'"]
    assert pkgs["purewheel"].version == "3.1"
    assert pkgs["purewheel"].markers == ["python_version >= '3.11'"]
    assert pkgs["gitdep"].skip == "git"
    assert pkgs["localpkg"].skip == "path"
    assert pkgs["archivepkg"].skip == "file"
    assert pkgs["editablepkg"].skip == "editable"
    assert all(p.origin == "Pipfile.lock" for p in src.packages)
    assert all(p.files is None for p in src.packages)
    assert all(pkgs[name].skip is None for name in ("fastlib", "winonly", "purewheel"))
    assert all(pkgs[name].version is None for name in ("gitdep", "localpkg", "archivepkg", "editablepkg"))


@pytest.mark.parametrize("section", ["default", "develop"])
def test_pipfile_lock_with_one_section(tmp_path, section):
    path = tmp_path / "Pipfile.lock"
    path.write_text(json.dumps({section: {"purewheel": {"version": "==3.1"}}}), encoding="utf-8")
    (src,) = load_inputs([str(path)])
    assert [(p.name, p.version) for p in src.packages] == [("purewheel", "3.1")]


def test_pipfile_lock_package_in_both_sections(tmp_path):
    path = tmp_path / "Pipfile.lock"
    lock = {
        "default": {
            "certifi": {"version": "==2025.1.31"},
            "colorama": {"version": "==0.4.6", "markers": "os_name == 'nt'"},
        },
        "develop": {
            "Certifi": {"version": "==2025.1.31"},
            "colorama": {"version": "==0.4.6", "markers": "sys_platform == 'win32'"},
            "pytest": {"version": "==8.3.5"},
        },
    }
    path.write_text(json.dumps(lock), encoding="utf-8")
    (src,) = load_inputs([str(path)])
    assert [(p.name, p.version) for p in src.packages] == [
        ("certifi", "2025.1.31"),
        ("colorama", "0.4.6"),
        ("pytest", "8.3.5"),
    ]
    assert by_name(src)["colorama"].markers == ["os_name == 'nt'", "sys_platform == 'win32'"]


def test_empty_pipfile_lock(tmp_path):
    path = tmp_path / "Pipfile.lock"
    path.write_text("{}", encoding="utf-8")
    (src,) = load_inputs([str(tmp_path)])
    assert src.label == "Pipfile.lock"
    assert src.packages == []


def test_adhoc_specs():
    (src,) = load_inputs(["numpy==2.3.4", "psycopg2"])
    assert [(p.name, p.version) for p in src.packages] == [("numpy", "2.3.4"), ("psycopg2", None)]


def test_wildcard_pin_is_not_a_pin():
    (src,) = load_inputs(["numpy==2.*"])
    assert src.packages[0].version is None


def test_missing_file_errors():
    with pytest.raises(SourceError, match="no such file"):
        load_inputs(["nope/uv.lock"])


def test_no_lockfile_in_dir(fixtures):
    with pytest.raises(SourceError, match="no lockfile found"):
        find_lockfile(fixtures / "empty")


def test_bad_requirement():
    with pytest.raises(SourceError):
        load_inputs(["not a valid ! spec"])


def test_pdm_lock_extras_variants_count_once(tmp_path):
    # PDM writes one entry per extras variant (seen in PDM's own lockfile for coverage[toml]).
    (tmp_path / "pdm.lock").write_text(
        '[[package]]\nname = "coverage"\nversion = "7.13.5"\nmarker = "sys_platform == \'linux\'"\n'
        'files = [{file = "coverage-7.13.5.tar.gz", hash = "sha256:00"}]\n\n'
        '[[package]]\nname = "coverage"\nversion = "7.13.5"\nextras = ["toml"]\n'
        'files = [{file = "coverage-7.13.5.tar.gz", hash = "sha256:00"}]\n',
        encoding="utf-8",
    )
    (src,) = load_inputs([str(tmp_path)])
    assert [(p.name, p.version) for p in src.packages] == [("coverage", "7.13.5")]
    assert src.packages[0].markers is None  # the unconditional variant wins


def test_requirements_bare_vcs_urls_are_skipped(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text(
        "git+ssh://git@github.com/org/repo.git#egg=foo\n"  # the "@" in git@ used to abort the whole run
        "hg+https://hg.example.com/bar#egg=bar&subdirectory=src\n"
        "https://example.com/pkgs/baz-1.0.tar.gz\n"
        "named @ git+https://github.com/org/named.git\n"
        "requests==2.32.3\n",
        encoding="utf-8",
    )
    (src,) = load_inputs([str(path)])
    got = {p.name: (p.skip, p.version) for p in src.packages}
    assert got["foo"] == ("url", None) and got["bar"] == ("url", None)
    assert got["https://example.com/pkgs/baz-1.0.tar.gz"] == ("url", None)
    assert got["named"] == ("url", None)
    assert got["requests"] == (None, "2.32.3")


def test_uv_path_dependency_is_not_a_root(tmp_path):
    # winhelper is a path dependency only installed on Windows; its own dependency must follow suit.
    (tmp_path / "uv.lock").write_text(
        'version = 1\n\n[[package]]\nname = "app"\nversion = "0"\nsource = { editable = "." }\n'
        'dependencies = [{ name = "winhelper", marker = "sys_platform == \'win32\'" }]\n\n'
        '[[package]]\nname = "winhelper"\nversion = "1"\nsource = { directory = "libs/winhelper" }\n'
        'dependencies = [{ name = "pywin32" }]\n\n'
        '[[package]]\nname = "pywin32"\nversion = "311"\nsource = { registry = "https://pypi.org/simple" }\n'
        'wheels = [{ url = "https://files.pythonhosted.org/p/pywin32-311-cp313-cp313-win_amd64.whl" }]\n',
        encoding="utf-8",
    )
    (src,) = load_inputs([str(tmp_path)])
    lin, win = build_targets(["3.13"], ["linux-x86_64", "win-amd64"])
    rows = {r.package.name: r for r in check([src], [lin, win])}
    assert rows["pywin32"].results == {lin: Status.NOT_NEEDED, win: Status.WHEEL}


def test_poetry_dict_markers_with_an_unconditional_group(tmp_path):
    (tmp_path / "poetry.lock").write_text(
        '[[package]]\nname = "colorama"\nversion = "0.4.6"\ngroups = ["main", "dev"]\n'
        'markers = { main = "sys_platform == \\"win32\\"" }\nfiles = []\n\n[metadata]\nlock-version = "2.1"\n',
        encoding="utf-8",
    )
    (src,) = load_inputs([str(tmp_path)])
    assert src.packages[0].markers is None  # dev always installs it, so it's needed everywhere


def test_poetry_1x_lock_walks_dependency_markers(tmp_path):
    # Before lock-version 2.1, markers only sit on dependency edges.
    (tmp_path / "poetry.lock").write_text(
        '[[package]]\nname = "app-lib"\nversion = "1.0"\n\n[package.dependencies]\n'
        'pywin32 = {version = ">=300", markers = "sys_platform == \\"win32\\""}\nrequests = "*"\n\n'
        '[[package]]\nname = "pywin32"\nversion = "306"\nfiles = []\n\n'
        '[[package]]\nname = "requests"\nversion = "2.32.3"\nfiles = []\n\n'
        '[metadata]\nlock-version = "1.1"\n',
        encoding="utf-8",
    )
    (src,) = load_inputs([str(tmp_path)])
    lin, win = build_targets(["3.13"], ["linux-x86_64", "win-amd64"])
    rows = {r.package.name: r for r in check([src], [lin, win])}
    assert rows["pywin32"].results[lin] is Status.NOT_NEEDED  # used to be a false "missing" on Linux
    assert rows["pywin32"].results[win] is not Status.NOT_NEEDED
    assert rows["requests"].results[lin] is not Status.NOT_NEEDED


def test_poetry_package_without_files_is_looked_up(tmp_path):
    (tmp_path / "poetry.lock").write_text(
        '[[package]]\nname = "x"\nversion = "1"\n\n[metadata]\nlock-version = "2.1"\n'
    )
    (src,) = load_inputs([str(tmp_path)])
    assert src.packages[0].files is None  # not [] (which would mean "can't install")


def test_requirements_parsing_edge_cases(tmp_path):
    (tmp_path / "more.txt").write_text("purewheel==3.1\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text(
        "-rmore.txt\n"  # no space: used to be silently dropped
        "fastlib==2.0.0 \\\n    --hash sha256:00\n"  # --hash with a space used to abort the run
        "nowheels==0.9\t# a comment after a tab used to abort the run\n"
        "requests==2.32.3\t# see https://docs.python-requests.org\n"  # used to be skipped as a URL
        "named@https://example.com/named-1.0.tar.gz\n"
        "git+https://example.com/repo.git#subdirectory=src&egg=deep ; python_version >= '3.10'\n",
        encoding="utf-8",
    )
    (src,) = load_inputs([str(tmp_path / "requirements.txt")])
    got = {p.name: (p.version, p.skip) for p in src.packages}
    assert got["purewheel"] == ("3.1", None)
    assert got["fastlib"] == ("2.0.0", None)
    assert got["nowheels"] == ("0.9", None)
    assert got["requests"] == ("2.32.3", None)
    assert got["named"] == (None, "url")
    assert got["deep"] == (None, "url")
