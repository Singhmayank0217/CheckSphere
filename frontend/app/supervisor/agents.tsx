import UsersPage from "@/src/portal/UsersPage";

export default function Team() {
  return <UsersPage roles={["agent"]} readOnly />;
}
