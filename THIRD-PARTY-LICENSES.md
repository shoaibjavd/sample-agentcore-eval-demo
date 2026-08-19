# Third-Party Licences

Generated from the CycloneDX SBOMs in `docs/sbom/`, which are produced from the
installed environment of each built container image rather than from the declared
dependency list. Transitive dependencies are therefore included.

- Agent image: **141** components
- MCP server image: **71** components
- Distinct across both: **172**


## Licence distribution

| Licence | Components |
|---|---|
| Apache-2.0 | 82 |
| MIT | 46 |
| BSD-3-Clause | 16 |
| License :: OSI Approved :: BSD License | 5 |
| License :: OSI Approved :: Apache Software License | 5 |
| not declared in metadata | 4 |
| BSD-2-Clause | 3 |
| ISC | 2 |
| PSF-2.0 | 2 |
| MPL-2.0 | 1 |
| MIT-0 | 1 |
| Apache-2.0 OR BSD-3-Clause | 1 |
| Unlicense | 1 |
| Apache-2.0 OR BSD-2-Clause | 1 |
| Apache-2.0 AND MIT | 1 |
| MIT-CMU | 1 |

## Notes

**`certifi` is MPL-2.0** — the only component under a copyleft licence. MPL-2.0 is file-level copyleft: it obliges you to publish modifications to the covered files. `certifi` is consumed unmodified as a CA bundle, so no such obligation arises. It is a transitive dependency of `requests`/`httpx` and is present in effectively every Python HTTP client stack.

**Four components declare no licence in their package metadata.** `assistant-agent` and `mcp-server` are the two first-party packages in this repository, covered by the `LICENSE` file at the root. `multidict` is Apache-2.0 and `protobuf` is BSD-3-Clause upstream; neither ships the classifier in a form the SBOM generator reads, so they appear as undeclared rather than unlicensed.

**No GPL, AGPL, LGPL, EPL, CDDL, SSPL, OSL or EUPL components are present.**


## Regenerating

The SBOMs are produced inside each image so that the recorded versions are the ones that actually ship. The generator is installed into a separate virtual environment: installing it into the image environment would add its own dependencies to the very environment being scanned, inflating the component count.

```sh
docker run --rm --user 0:0 --entrypoint sh <image> -c '
  python3 -m venv /tmp/sbomtool
  /tmp/sbomtool/bin/pip install cyclonedx-bom
  /tmp/sbomtool/bin/cyclonedx-py environment /usr/local --output-format JSON
' > sbom.json
```


_Component data verified 2026-08-20; counts cross-checked against `pip list` inside each image._
