// Build-variant switch on top of app.json (Expo passes app.json's "expo" object in as `config`).
//
//   APP_VARIANT absent  -> production: "CheckSphere", com.checksphere.app, scheme "checksphere" (app.json as-is)
//   APP_VARIANT=preview -> LAN test build: "CheckSphere (Preview)", com.checksphere.app.preview, "checksphere-preview"
//
// The preview build has its own package ID, so Android treats it as a separate app with its own signing key: it can be
// installed next to the production app and can never replace it on a staff phone. Only identity fields change here;
// everything else (permissions, versionCode, icons, splash, plugins) comes from app.json unchanged.
//
// Firebase (remote push on Android): EAS provides google-services.json as the secret file variable GOOGLE_SERVICES_JSON
// (its value is the path of the file on the build machine). The file is never committed. Without it the app builds
// and runs normally, only without remote push.
const VARIANTS = {
  preview: {
    name: "CheckSphere (Preview)",
    id: "com.checksphere.app.preview",
    scheme: "checksphere-preview",
  },
};

function withFirebase(config) {
  const file = (process.env.GOOGLE_SERVICES_JSON || "").trim();
  if (!file) return config;
  return { ...config, android: { ...config.android, googleServicesFile: file } };
}

module.exports = ({ config }) => {
  const key = (process.env.APP_VARIANT || "").trim().toLowerCase();
  if (!key || key === "production") return withFirebase(config);
  const v = VARIANTS[key];
  if (!v) throw new Error(`Unknown APP_VARIANT "${process.env.APP_VARIANT}" (expected "preview" or unset)`);
  return withFirebase({
    ...config,
    name: v.name,
    scheme: v.scheme,
    ios: { ...config.ios, bundleIdentifier: v.id },
    android: { ...config.android, package: v.id },
  });
};
