import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { errorMessage } from "@/lib/api";
import { Button, Card, ErrorBox, Field, Input } from "@/components/ui";

const schema = z.object({
  email: z.string().min(1, "Enter your email"),
  password: z.string().min(1, "Enter your password"),
});
type Form = z.infer<typeof schema>;

export default function Login() {
  const { login, config } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema) });

  const onSubmit = async (v: Form) => {
    setError(null);
    try {
      await login(v.email, v.password);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-background to-accent p-4">
      <Card className="w-full max-w-sm p-6">
        <div className="mb-6 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">TQ</div>
          <div>
            <h1 className="text-lg font-semibold">{config?.app_name ?? "TouQA AI"}</h1>
            <p className="text-xs text-muted-foreground">AI QA agent for Spira and Jira</p>
          </div>
        </div>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <Field label="Email" error={formState.errors.email?.message}>
            <Input type="email" autoComplete="username" autoFocus {...register("email")} />
          </Field>
          <Field label="Password" error={formState.errors.password?.message}>
            <Input type="password" autoComplete="current-password" {...register("password")} />
          </Field>
          {error && <ErrorBox error={error} />}
          <Button type="submit" className="w-full" loading={formState.isSubmitting}>Sign in</Button>
        </form>
        <p className="mt-4 text-center text-[11px] text-muted-foreground">
          The admin account is configured in the backend <code>.env</code> file.
        </p>
      </Card>
    </div>
  );
}
