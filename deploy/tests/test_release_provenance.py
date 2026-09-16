import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
EXPECTED_BUILD_ARG = "BUILD_COMMIT: ${DEPLOYMENT_RELEASE:?set by deploy/"


class ReleaseProvenanceContractTests(unittest.TestCase):
    def test_deploys_derive_release_from_exact_checked_out_commit(self):
        for relative in ("deploy/deploy.sh", "deploy/observer-deploy.sh"):
            script = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(
                'export DEPLOYMENT_RELEASE="$(git rev-parse --verify \'HEAD^{commit}\')"',
                script,
            )
            self.assertIn("git status --porcelain --untracked-files=all", script)

    def test_compose_passes_one_build_release_and_has_no_runtime_override(self):
        cockpit = (ROOT / "docker-compose.deploy.yml").read_text(encoding="utf-8")
        observer = (ROOT / "docker-compose.observer.yml").read_text(encoding="utf-8")
        self.assertIn(EXPECTED_BUILD_ARG + "deploy.sh}", cockpit)
        self.assertIn(EXPECTED_BUILD_ARG + "observer-deploy.sh}", observer)
        for compose in (cockpit, observer):
            self.assertIsNone(
                re.search(r"^\s+(?:COCKPIT_RELEASE|PLENORA_OBSERVER_RELEASE):", compose, re.M)
            )

    def test_images_bake_release_into_runtime_and_revision_label(self):
        expectations = {
            "backend/Dockerfile": "COCKPIT_RELEASE=${BUILD_COMMIT}",
            "collector/Dockerfile": "COCKPIT_RELEASE=${BUILD_COMMIT}",
            "observer/Dockerfile": "PLENORA_OBSERVER_RELEASE=${BUILD_COMMIT}",
            "frontend/Dockerfile": "NEXT_PUBLIC_COCKPIT_RELEASE=${BUILD_COMMIT}",
        }
        for relative, runtime_env in expectations.items():
            dockerfile = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("ARG BUILD_COMMIT=development", dockerfile)
            self.assertIn(runtime_env, dockerfile)
            self.assertIn("org.opencontainers.image.revision=${BUILD_COMMIT}", dockerfile)

        frontend_production = (ROOT / "frontend/Dockerfile").read_text(
            encoding="utf-8"
        ).split("FROM node:22.18.0-alpine AS production", maxsplit=1)[1]
        self.assertIn("ARG BUILD_COMMIT=development", frontend_production)
        self.assertIn("NEXT_PUBLIC_COCKPIT_RELEASE=${BUILD_COMMIT}", frontend_production)
        self.assertIn("org.opencontainers.image.revision=${BUILD_COMMIT}", frontend_production)

    def test_legacy_manual_release_values_are_not_part_of_env_templates(self):
        for relative in (".env.deploy.example", ".env.observer.example"):
            template = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("COCKPIT_RELEASE=", template)
            self.assertNotIn("PLENORA_OBSERVER_RELEASE=", template)


if __name__ == "__main__":
    unittest.main()
