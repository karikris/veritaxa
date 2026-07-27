export type Json = string | number | boolean | null | { [key: string]: Json | undefined } | Json[];

export type Database = {
  public: {
    Tables: {
      image_reviews: {
        Row: {
          client_version: string;
          comment: string | null;
          created_at: string;
          id: string;
          identifiedBy: string;
          item_id: string;
          label: Database['public']['Enums']['review_label'];
          reviewer_id: string;
          submission_id: string;
        };
        Insert: never;
        Update: never;
        Relationships: [];
      };
      review_batches: {
        Row: {
          batch_code: string;
          campaign_id: string;
          closed_at: string | null;
          created_at: string;
          id: string;
          opened_at: string | null;
          position: number;
          reviewer_name: string;
          status: Database['public']['Enums']['batch_status'];
        };
        Insert: never;
        Update: never;
        Relationships: [];
      };
      review_campaigns: {
        Row: {
          campaign_code: string;
          created_at: string;
          id: string;
          internal_name: string;
          reviewer_name: string;
          source_provider: string | null;
          status: Database['public']['Enums']['campaign_status'];
          target_scientific_name: string | null;
          target_taxon_key: string | null;
          updated_at: string;
        };
        Insert: never;
        Update: never;
        Relationships: [];
      };
      review_items: {
        Row: {
          batch_id: string;
          created_at: string;
          display_url: string | null;
          flickr_search_term: string | null;
          id: string;
          image_id: string;
          image_url: string;
          pipeline_metadata: Json | null;
          position: number;
          source_labels: Json | null;
          source_page_url: string | null;
          source_provider: string;
          source_record_id: string | null;
        };
        Insert: never;
        Update: never;
        Relationships: [];
      };
    };
    Views: Record<string, never>;
    Functions: {
      get_review_queue: {
        Args: { p_batch_id: string; p_limit?: number };
        Returns: {
          display_url: string | null;
          fallback_image_url: string;
          image_id: string;
          item_id: string;
          position: number;
          reviewed_count: number;
          total_count: number;
        }[];
      };
      is_authorized_reviewer: {
        Args: Record<PropertyKey, never>;
        Returns: boolean;
      };
      list_review_batches: {
        Args: Record<PropertyKey, never>;
        Returns: {
          batch_code: string;
          batch_id: string;
          complete: boolean;
          reviewed_count: number;
          reviewer_name: string;
          total_count: number;
        }[];
      };
      submit_image_review: {
        Args: {
          p_client_version: string;
          p_comment: string | null;
          p_item_id: string;
          p_label: Database['public']['Enums']['review_label'];
          p_submission_id: string;
        };
        Returns: {
          complete: boolean;
          reviewed_count: number;
          total_count: number;
        }[];
      };
    };
    Enums: {
      batch_status: 'draft' | 'open' | 'closed' | 'archived';
      campaign_status: 'draft' | 'open' | 'closed' | 'archived';
      review_label:
        | 'adult_butterfly'
        | 'caterpillar'
        | 'moth'
        | 'other_insect'
        | 'arachnid'
        | 'other_arthropod'
        | 'plant'
        | 'mammal_or_person'
        | 'bird'
        | 'other_animal'
        | 'fungus'
        | 'artifact_or_illustration'
        | 'no_biological_subject'
        | 'uncertain'
        | 'image_unavailable';
    };
    CompositeTypes: Record<string, never>;
  };
};
