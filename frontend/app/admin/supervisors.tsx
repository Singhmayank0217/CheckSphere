import UsersPage from "@/src/portal/UsersPage";

export default function Supervisors() {
  return <UsersPage roles={["supervisor", "super_admin"]} />;
}
